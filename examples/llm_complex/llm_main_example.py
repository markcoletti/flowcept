# The code in example file is based on:
# https://blog.paperspace.com/build-a-language-model-using-pytorch/
import argparse
import json
import sys
import itertools
import yaml
import os
import uuid
import pandas as pd
from time import sleep

from examples.llm_complex.llm_dataprep import dataprep_workflow
from examples.llm_complex.llm_model import model_train
from flowcept.commons.utils import replace_non_serializable_times
from flowcept.flowceptor.adapters.dask.dask_plugins import register_dask_workflow
from flowcept.configs import MONGO_ENABLED, INSTRUMENTATION
from flowcept import Flowcept



def generate_configs(params: dict):
    """
    Generate a list of configurations by computing the Cartesian product of list-valued parameters
    while keeping constant parameters unchanged.

    Parameters
    ----------
    params : dict
        A dictionary where keys are parameter names and values can be either:
        - A list of possible values (for parameters to be expanded in the cross-product).
        - A single value (for constant parameters that remain unchanged across configurations).

    Returns
    -------
    list of dict
        A list of dictionaries, where each dictionary represents a unique configuration
        formed by combining the cross-product of list-valued parameters with the constant parameters.

    Examples
    --------
    >>> params = {
    ...     "a": [1, 2],
    ...     "b": [3, 4],
    ...     "c": "fixed"
    ... }
    >>> generate_configs(params)
    [{'a': 1, 'b': 3, 'c': 'fixed'},
     {'a': 1, 'b': 4, 'c': 'fixed'},
     {'a': 2, 'b': 3, 'c': 'fixed'},
     {'a': 2, 'b': 4, 'c': 'fixed'}]
    """
    result = []
    expanded_lists = []
    constants = {}
    for p in params:
        vals = params[p]
        if isinstance(vals, list):
            expanded = [{p: v} for v in vals]
            expanded_lists.append(expanded)
        else:
            constants[p] = vals

    cross_product = [{k: v for d in combo for k, v in d.items()}
                     for combo in itertools.product(*expanded_lists)]
    for c in cross_product:
        config = c.copy()
        config.update(constants)
        result.append(config)
    return result


def search_workflow(ntokens, dataset_ref, train_data_path, val_data_path, test_data_path, workflow_params, campaign_id=None, scheduler_file=None, start_dask_cluster=False, with_persistence=True):
    client, cluster = start_dask(scheduler_file, start_dask_cluster)
    workflow_params["train_data_path"] = train_data_path
    workflow_params["val_data_path"] = val_data_path
    workflow_params["test_data_path"] = test_data_path

    configs = generate_configs(workflow_params)
    configs = [
        {**c, "ntokens": ntokens,
         "dataset_ref": dataset_ref,
         "train_data_path": train_data_path,
         "val_data_path": val_data_path,
         "test_data_path": test_data_path,
         "campaign_id": campaign_id}
        for c in configs
    ]

    # Start Flowcept's Dask observer
    with Flowcept("dask", start_persistence=with_persistence):

        # Registering a Dask workflow in Flowcept's database
        search_wf_id = register_dask_workflow(client, used=workflow_params,
                                              workflow_name="model_search",
                                              campaign_id=campaign_id)
        print(f"search_workflow_id={search_wf_id}")

        max_runs = workflow_params.get("max_runs", None)

        for conf in configs[:max_runs]:  # Edit here to enable more runs
            t = client.submit(model_train, workflow_id=search_wf_id, **conf)
            print(t.result())

        print("Done main loop. Closing dask...")
        close_dask(client, cluster, scheduler_file, start_dask_cluster)
        print("Closed Dask. Closing Flowcept...")
        print("Closed.")
    return search_wf_id


def start_dask(scheduler_file=None, start_dask_cluster=False):
    from distributed import Client
    from flowcept.flowceptor.adapters.dask.dask_plugins import FlowceptDaskWorkerAdapter

    if start_dask_cluster:
        import subprocess
        import signal

        def run_command(command, out_file="./cmd.out", err_file="./cmd.err"):
            with open(out_file, "w") as out, open(err_file, "w") as err:
                process = subprocess.Popen(
                    ["/bin/bash", "-c", command],
                    stdout=out,
                    stderr=err,
                    preexec_fn=os.setsid
                )

            def terminate_child():
                """Terminate the child process group when the parent exits."""
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)

            import atexit
            atexit.register(terminate_child)  # Ensure cleanup on exit

            return process

        print("Starting Dask Cluster with command line.")
        scheduler_file = "scheduler_file.json"
        print("Killing any old dask clusters.")
        run_command("pkill -f dask")
        sleep(3)
        run_command(f"dask scheduler --no-dashboard --no-show --scheduler-file {scheduler_file}")

        sleep(2)
        run_command(
            f"dask worker --nthreads 1 --nworkers 1 --no-dashboard  --scheduler-file {scheduler_file}",
            "worker.out",
            "worker.err"
        )
        sleep(5)
        assert os.path.exists(scheduler_file)
        print(f"{scheduler_file} created!")

    if scheduler_file is None:
        from distributed import LocalCluster
        cluster = LocalCluster(n_workers=1)
        scheduler = cluster.scheduler
        client = Client(scheduler.address)
        client.forward_logging()
        # Registering Flowcept's worker adapters
        client.register_plugin(FlowceptDaskWorkerAdapter())
    else:
        print(f"Starting with Scheduler File {scheduler_file}!")
        # If scheduler file is provided, this cluster is not managed in this code.
        client = Client(scheduler_file=scheduler_file)
        print("Started Client.")
        client.register_plugin(FlowceptDaskWorkerAdapter())
        cluster = None
        print("Registered plugin.")
    return client, cluster


def close_dask(client, cluster, scheduler_file=None, start_dask_cluster=False):
    if start_dask_cluster or scheduler_file:
        client.close()
        # client.shutdown() # We are getting an error here...
        sleep(10)
    else:
        client.close()
        cluster.close()


def run_asserts_and_exports(campaign_id, model_search_wf_id):
    from flowcept.commons.vocabulary import Status
    print("Now running all asserts...")
    """
    # TODO revisit
    This works as follows:
    Campaign:
        Data Prep Workflow
        Search Workflow

        Workflows:
            Data Prep Workflow
            Search workflow ->
              Module Layer Forward Train Workflow
              Module Layer Forward Test Workflow

    Tasks:
        Main workflow . Main model_train task (dask task) ->
            Main workflow . Epochs Whole Loop
                Main workflow . Loop Iteration Task
                    Module Layer Forward Train Workflow . Parent module forward tasks
                        Module Layer Forward Train Workflow . Children modules forward
            Module Layer Forward Test Workflow . Parent module forward tasks
                Module Layer Forward Test Workflow . Children modules forward tasks
    """

    if INSTRUMENTATION.get("torch").get("epoch_loop") is None or INSTRUMENTATION.get("torch").get("batch_loop") is None:
        raise Exception("We can't assert this now.")

    at_every = INSTRUMENTATION.get("torch").get("capture_epochs_at_every", 1)
    campaign_workflows = Flowcept.db.query({"campaign_id": campaign_id}, collection="workflows")
    workflows_data = []
    assert len(campaign_workflows) == 4 - 1  # dataprep + model_search + 2 subworkflows for the model_seearch
    model_search_wf = dataprep_wf = None
    for w in campaign_workflows:
        workflows_data.append(w)
        if w["name"] == "model_search":
            model_search_wf = w
        elif w["name"] == "generate_wikitext_dataset":
            dataprep_wf = w
    assert dataprep_wf["generated"]["train_data_path"]
    assert dataprep_wf["generated"]["test_data_path"]
    assert dataprep_wf["generated"]["val_data_path"]

    mswf = Flowcept.db.query({"workflow_id": model_search_wf_id}, collection="workflows")[0]
    assert model_search_wf == mswf

    parent_module_wfs = Flowcept.db.query({"parent_workflow_id": model_search_wf_id},
                                          collection="workflows")
    assert len(parent_module_wfs) == 1
    parent_module_wf = parent_module_wfs[0]
    workflows_data.append(parent_module_wf)
    parent_module_wf_id = parent_module_wf["workflow_id"]

    n_tasks_expected = 0
    model_train_tasks = Flowcept.db.query(
        {"workflow_id": model_search_wf_id, "activity_id": "model_train"})
    assert len(model_train_tasks) == model_search_wf["used"]["max_runs"]
    for t in model_train_tasks:
        n_tasks_expected += 1
        assert t["status"] == Status.FINISHED.value

        epoch_iteration_tasks = Flowcept.db.query(
            {"parent_task_id": t["task_id"], "activity_id": "epochs_loop_iteration"})
        assert len(epoch_iteration_tasks) == t["used"]["epochs"]

        epoch_iteration_ids = set()
        for epoch_iteration_task in epoch_iteration_tasks:
            n_tasks_expected += 1
            epoch_iteration_ids.add(epoch_iteration_task["task_id"])
            assert epoch_iteration_task["status"] == Status.FINISHED.value

            train_batch_iteration_tasks = Flowcept.db.query(
                {"parent_task_id": epoch_iteration_task["task_id"], "activity_id": "train_batch_iteration"})

            assert len(train_batch_iteration_tasks) > 0  # TODO: == number of train_batches

            eval_batch_iteration_tasks = Flowcept.db.query(
                {"parent_task_id": epoch_iteration_task["task_id"],
                 "activity_id": "eval_batch_iteration"})
            assert len(eval_batch_iteration_tasks) > 0  # TODO: == number of eval_batches

            batch_iteration_lst = [train_batch_iteration_tasks, eval_batch_iteration_tasks]
            for batch_iterations in batch_iteration_lst:

                for batch_iteration in batch_iterations:
                    n_tasks_expected += 1

                    if "parent" in INSTRUMENTATION.get("torch").get("what"):

                        parent_forwards = Flowcept.db.query(
                            {"workflow_id": parent_module_wf_id, "activity_id": "TransformerModel", "parent_task_id": batch_iteration["task_id"]})

                        if len(parent_forwards) == 0:
                            continue

                        assert len(parent_forwards) == 1
                        parent_forward = parent_forwards[0]

                        n_tasks_expected += 1
                        assert parent_forward["workflow_id"] == parent_module_wf_id
                        assert parent_forward["status"] == Status.FINISHED.value
                        assert parent_module_wf["custom_metadata"]["model_profile"]
                        assert parent_forward[
                                   "parent_task_id"] == batch_iteration["task_id"]

                        if "children" in INSTRUMENTATION.get("torch").get("what"):
                            children_forwards = Flowcept.db.query(
                                {"parent_task_id": parent_forward["task_id"]})

                            # We only have children_forward if:
                            # epoch == 1 or
                            # telemetry and epoch % at every == 0
                            curr_epoch = epoch_iteration_task["used"]["i"]
                            if  (curr_epoch == 0) or \
                                ("telemetry" in INSTRUMENTATION.get("torch").get("children_mode") and curr_epoch % at_every == 0):
                                assert len(children_forwards) == 4  # There are 4 children submodules # TODO get dynamically
                                for child_forward in children_forwards:
                                    n_tasks_expected += 1
                                    assert child_forward["status"] == Status.FINISHED.value
                                    assert child_forward["workflow_id"] == parent_module_wf_id
                            else:
                                assert len(children_forwards) == 0

    n_workflows_expected = len(campaign_workflows)
    return n_workflows_expected, n_tasks_expected


def save_files(mongo_dao, campaign_id, model_search_wf_id, output_dir="output_data"):
    os.makedirs(output_dir, exist_ok=True)
    best_task = Flowcept.db.query({"workflow_id": model_search_wf_id, "activity_id": "model_train"}, limit=1,
                                  sort=[("generated.test_loss", Flowcept.db.ASCENDING)])[0]
    replace_non_serializable_times(best_task)
    workflow_result = {
        "campaign_id": campaign_id,
        "best_task_id": best_task["task_id"],
        "workflow_id": best_task["workflow_id"],
        "best_hyperparameters": best_task["used"],
        "best_loss": best_task["generated"]["test_loss"],
        "best_obj_id": best_task["generated"]["best_obj_id"],
        "best_generated": best_task["generated"],
        "best_task_data": best_task,
    }
    with open(f"{output_dir}/workflow_result.json", "w") as f:
        json.dump(workflow_result, f, indent=2)

    delete_after_run = best_task["used"].get("delete_after_run", True)
    if delete_after_run:
        best_model_obj_id = best_task["generated"]["best_obj_id"]
        print("Deleting best model from the database.")
        mongo_dao.delete_object_keys("object_id", [best_model_obj_id])

    workflows_file = f"{output_dir}/workflows_{uuid.uuid4()}.json"
    print(f"workflows_file = '{workflows_file}'")
    Flowcept.db.dump_to_file(filter={"campaign_id": campaign_id}, collection="workflows",
                             output_file=workflows_file)
    tasks_file = f"{output_dir}/tasks_{uuid.uuid4()}.parquet"
    print(f"tasks_file = '{tasks_file}'")

    mapping_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'custom_provenance_id_mapping.yaml')
    with open(mapping_path) as f:
        mapping = yaml.safe_load(f)
    Flowcept.db.dump_tasks_to_file_recursive(workflow_id=model_search_wf_id, output_file=tasks_file, mapping=mapping)

    return workflows_file, tasks_file


def run_campaign(workflow_params, campaign_id=None, scheduler_file=None, start_dask_cluster=False, with_persistence=True):

    _campaign_id = campaign_id or str(uuid.uuid4())
    print(f"Campaign id={_campaign_id}")
    tokenizer_type = workflow_params["tokenizer_type"]
    subset_size = workflow_params.get("subset_size", None)

    _dataprep_wf_id, dataprep_generated = dataprep_workflow(
        data_dir=workflow_params["input_data_dir"],
        campaign_id=_campaign_id,
        tokenizer_type=tokenizer_type,
        batch_size=workflow_params["batch_size"],
        eval_batch_size=workflow_params["eval_batch_size"],
        subset_size=subset_size,
        with_persistence=with_persistence)

    _search_wf_id = search_workflow(dataprep_generated["ntokens"], dataprep_generated["dataset_ref"], dataprep_generated["train_data_path"], dataprep_generated["val_data_path"], dataprep_generated["test_data_path"], workflow_params, campaign_id=_campaign_id, scheduler_file=scheduler_file, start_dask_cluster=start_dask_cluster, with_persistence=with_persistence)

    return _campaign_id, _dataprep_wf_id, _search_wf_id, dataprep_generated["train_n_batches"], dataprep_generated["val_n_batches"]


def asserts_on_saved_dfs(mongo_dao, workflows_file, tasks_file, n_workflows_expected, n_tasks_expected, epoch_iterations, max_runs, n_batches_train, n_batches_eval, n_modules, delete_after_run):
    workflows_df = pd.read_json(workflows_file)
    # Assert workflows dump
    assert len(workflows_df) == n_workflows_expected
    tasks_df = pd.read_parquet(tasks_file)
    print(len(tasks_df), n_tasks_expected)
    #assert len(tasks_df) == n_tasks_expected

    # TODO: save #n_batches for train, test, val individually
    search_tasks = max_runs
    at_every = INSTRUMENTATION.get("torch").get("capture_epochs_at_every", 1)

    batch_iteration_tasks = epoch_iterations * (n_batches_train + n_batches_eval)
    non_module_tasks = search_tasks + epoch_iterations + batch_iteration_tasks

    parent_module_tasks = batch_iteration_tasks
    parent_module_tasks = parent_module_tasks/at_every
    expected_non_child_tasks = non_module_tasks + parent_module_tasks

    assert len(tasks_df[tasks_df.subtype != 'child_forward']) == expected_non_child_tasks

    number_of_captured_epochs = epoch_iterations / at_every

    if "telemetry" in INSTRUMENTATION.get("torch").get("children_mode"):
        expected_child_tasks = search_tasks * epoch_iterations * (
                    (n_batches_train * n_modules) + (n_batches_eval * n_modules))
        expected_child_tasks = expected_child_tasks/at_every
        expected_child_tasks_per_epoch = expected_child_tasks / number_of_captured_epochs
        with_used = 1 * expected_child_tasks_per_epoch
        without_used = (number_of_captured_epochs - 1) * expected_child_tasks_per_epoch
    elif "tensor_inspection" in INSTRUMENTATION.get("torch").get("children_mode"):
        expected_child_tasks = search_tasks * 1 * (
                    (n_batches_train * n_modules) + (n_batches_eval * n_modules))
        expected_child_tasks_per_epoch = expected_child_tasks
        with_used = 1 * expected_child_tasks_per_epoch
        without_used = 0
    else:
        raise NotImplementedError("Needs to implement for lightweight")

    # Testing if only the first epoch got the inspection
    assert len(tasks_df[(tasks_df.subtype == 'parent_forward') & (tasks_df.used.str.contains('tensor'))]) == n_batches_train + n_batches_eval

    if "children" in INSTRUMENTATION.get("torch").get("what"):
        assert len(tasks_df[tasks_df.subtype == 'child_forward']) == expected_child_tasks
        assert non_module_tasks + parent_module_tasks + expected_child_tasks == len(tasks_df)
        # Testing if capturing at every at_every epochs
        assert len(tasks_df[(tasks_df.subtype == 'child_forward') & (
                    tasks_df.used == 'NaN')]) == without_used
        assert len(
            tasks_df[(tasks_df.subtype == 'child_forward') & (tasks_df.used != 'NaN')]) == with_used

    task_ids = list(tasks_df["task_id"].unique())
    workflow_ids = list(workflows_df["workflow_id"].unique())

    if delete_after_run:
        print("Deleting generated data in MongoDB")
        mongo_dao.delete_task_keys("task_id", task_ids)
        mongo_dao.delete_workflow_keys("workflow_id", workflow_ids)


def verify_number_docs_in_db(mongo_dao, n_tasks=None, n_wfs=None, n_objects=None):
    _n_tasks = mongo_dao.count_tasks()
    _n_wfs = mongo_dao.count_workflows()
    _n_objects = mongo_dao.count_objects()

    if n_tasks:
        if n_tasks != _n_tasks:
            raise Exception("Number of tasks now is different than when we started this campaign.")
        else:
            print("Good, #tasks are equal to the beginning!")

    if n_wfs:
        if n_wfs != _n_wfs:
            raise Exception("Number of workflows now is different than when we started this campaign.")
        else:
            print("Good, #workflows are equal to the beginning!")

    if n_objects:
        if n_objects != _n_objects:
            raise Exception("Number of object now is different than when we started this campaign.")
        else:
            print("Good, #objects are equal to the beginning!")

    return _n_tasks, _n_wfs, _n_objects



def parse_args():
    parser = argparse.ArgumentParser(description="Submit Dask workflow.")

    arguments = parser.add_argument_group("arguments")
    arguments.add_argument("--scheduler-file", metavar="S", default=None, help="Dask's scheduler file")
    arguments.add_argument("--rep-dir", metavar="D", default="./output_data", help="Job's repetition directory")
    arguments.add_argument("--workflow-id", metavar="D", default=None, help="Wf Id")
    arguments.add_argument("--campaign-id", metavar="D", default=None, help="Campaign Id")
    true_values = {"true", "t", "1", "yes", "y"}
    arguments.add_argument(
        "--with-persistence",
        type=lambda v: v.lower() in true_values,
        default=True,
        help=f"Store data in MongoDB (accepts: {', '.join(true_values)})",
    )
    arguments.add_argument("--start-dask-cluster", action="store_true", default=False, help="Start the dask cluster before execution. Use only for tests and not for real experiments")
    default_exp_param_settings = {
        "input_data_dir": "./input_data",
        "batch_size": 20,
        "eval_batch_size": 10,
        "emsize": [200],
        "nhid": [200],
        "nlayers": [2],  # 2
        "nhead": [2],
        "dropout": [0.2],
        "lr": [0.1],
        "pos_encoding_max_len": [5000],
        "subset_size": 10,
        "epochs": 4,
        "max_runs": 1,
        "delete_after_run": True,
        "random_seed": 0,
        "tokenizer_type": "basic_english",   # spacy, moses, toktok, revtok, subword
    }

    arguments.add_argument(
        "--workflow-params",
        metavar="D",
        default=json.dumps(default_exp_param_settings),
        help="Workflow Parameters as a stringified dictionary",
    )
    args, _ = parser.parse_known_args()  # Ignore unknown arguments
    return args


def main():

    args = parse_args()
    print("Arguments:", args)
    workflow_params = json.loads(args.workflow_params)
    workflow_params["with_persistence"] = args.with_persistence
    delete_after_run = workflow_params.get("delete_after_run", True)
    print("TORCH SETTINGS: " + str(INSTRUMENTATION.get("torch")))

    if args.with_persistence:
        from flowcept.commons.daos.docdb_dao.mongodb_dao import MongoDBDAO
        mongo_dao = MongoDBDAO(create_indices=False)
        if delete_after_run:
            n_tasks, n_wfs, n_objects = verify_number_docs_in_db(mongo_dao)
    else:
        print("We are not going to persist this run!")
    campaign_id, dataprep_wf_id, model_search_wf_id, n_batches_train, n_batches_eval = run_campaign(workflow_params, campaign_id=args.campaign_id, scheduler_file=args.scheduler_file, start_dask_cluster=args.start_dask_cluster, with_persistence=args.with_persistence)

    if args.with_persistence:
        n_workflows_expected, n_tasks_expected = run_asserts_and_exports(campaign_id, model_search_wf_id)
        workflows_file, tasks_file = save_files(mongo_dao, campaign_id, model_search_wf_id, output_dir=args.rep_dir)
        # TODO: 4 is the number of modules of the current modules. We should get it dynamically.
        asserts_on_saved_dfs(mongo_dao, workflows_file, tasks_file, n_workflows_expected, n_tasks_expected,
                             workflow_params["epochs"], workflow_params["max_runs"], n_batches_train, n_batches_eval,
                             n_modules=4, delete_after_run=delete_after_run)
        if delete_after_run:
            verify_number_docs_in_db(mongo_dao, n_tasks, n_wfs, n_objects)

    print("Alright! Congrats.")


if __name__ == "__main__":

    if not MONGO_ENABLED:
        print("This test is only available if Mongo is enabled.")
        sys.exit(0)

    main()
    sys.exit(0)

