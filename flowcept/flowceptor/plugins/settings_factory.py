import os
import yaml

from flowcept.commons.vocabulary import Vocabulary
from flowcept.configs import (
    PROJECT_DIR_PATH,
    SETTINGS_PATH,
)

from flowcept.flowceptor.plugins.base_settings_dataclasses import (
    BaseSettings,
    KeyValue,
)
from flowcept.flowceptor.plugins.zambeze.zambeze_dataclasses import (
    ZambezeSettings,
)
from flowcept.flowceptor.plugins.mlflow.mlflow_dataclasses import (
    MLFlowSettings,
)
from flowcept.flowceptor.plugins.tensorboard.tensorboard_dataclasses import (
    TensorboardSettings,
)
from flowcept.flowceptor.plugins.dask.dask_dataclasses import (
    DaskSettings,
)


SETTINGS_CLASSES = {
    Vocabulary.Settings.ZAMBEZE_KIND: ZambezeSettings,
    Vocabulary.Settings.MLFLOW_KIND: MLFlowSettings,
    Vocabulary.Settings.TENSORBOARD_KIND: TensorboardSettings,
    Vocabulary.Settings.DASK_KIND: DaskSettings,
}


def _build_base_settings(kind: str, settings_dict: dict) -> BaseSettings:
    settings_obj = SETTINGS_CLASSES[kind](**settings_dict)
    if hasattr(settings_obj, "file_path") and not os.path.isabs(
        settings_obj.file_path
    ):
        settings_obj.file_path = os.path.join(
            PROJECT_DIR_PATH, settings_obj.file_path
        )

    # # Add default values for abstract settings here:
    # if settings_obj.enrich_messages is None:
    #     settings_obj.enrich_messages = True
    return settings_obj


def get_settings(plugin_key: str) -> BaseSettings:
    with open(SETTINGS_PATH) as f:
        data = yaml.load(f, Loader=yaml.FullLoader)
    settings_dict = data[Vocabulary.Settings.PLUGINS][plugin_key]
    if not settings_dict:
        raise Exception(
            f"You must specify the plugin <<{plugin_key}>> in"
            f" the settings YAML file."
        )
    settings_dict["key"] = plugin_key
    kind = settings_dict[Vocabulary.Settings.KIND]
    settings_obj = _build_base_settings(kind, settings_dict)

    # Add any specific setting builder below
    if kind == Vocabulary.Settings.ZAMBEZE_KIND:
        settings_obj.key_values_to_filter = [
            KeyValue(**item) for item in settings_obj.key_values_to_filter
        ]
    return settings_obj