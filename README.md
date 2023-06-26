[![Build](https://github.com/ORNL/flowcept/actions/workflows/create-release-n-publish.yml/badge.svg)](https://github.com/ORNL/flowcept/actions/workflows/create-release-n-publish.yml)
[![PyPI](https://badge.fury.io/py/flowcept.svg)](https://pypi.org/project/flowcept)
[![Tests](https://github.com/ORNL/flowcept/actions/workflows/run-tests.yml/badge.svg)](https://github.com/ORNL/flowcept/actions/workflows/run-tests.yml)
[![Code Formatting](https://github.com/ORNL/flowcept/actions/workflows/code-formatting.yml/badge.svg)](https://github.com/ORNL/flowcept/actions/workflows/code-formatting.yml)
[![License: MIT](https://img.shields.io/github/license/ORNL/flowcept)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# FlowCept

FlowCept is a system that integrates data at runtime from multiple workflows, allowing end-to-end data analyses. 
It is intended to address scenarios where multiple workflows in a science campaign or enterprise run and generate 
important data to be analyzed. Since these workflows may use different data generation tools or can be executed within
different parallel computing systems (e.g., Dask, Spark, workflow management systems), its key differentiator is the 
capability to seamless integrate data from various sources. By using provenance data management techniques, 
it builds an integrated data view at runtime of these multi-workflow data following 
[W3C PROV](https://www.w3.org/TR/prov-overview/) recommendations for its data schema.
By using data observability strategies, it does not require significant changes in user codes
or systems. All users need to do is to create adapters for their systems or tools. 

Currently, FlowCept provides adapters for: [Dask](https://www.dask.org/), [MLFlow](https://mlflow.org/), [TensorBoard](https://www.tensorflow.org/tensorboard), and [Zambeze](https://github.com/ORNL/zambeze). 

See the [Jupyter Notebooks](notebooks) for utilization examples.

See the [Contributing](CONTRIBUTING.md) file for guidelines to contribute with new adapters. Note that we may use the
term 'plugin' in the codebase as a synonym to adapter. Future releases should standardize the terminology to use adapter.


## Install and Setup:

1. Install FlowCept: 

`pip install .` in this directory (or `pip install flowcept`).

For convenience, this will install all dependencies for all adapters. But it can install
dependencies for adapters you will not use. For this reason, you may want to install 
like this: `pip install .[adapter_key]` for the adapters we have implemented, e.g., `pip install .[dask]`.
See [extra_requirements](extra_requirements) if you want to install the dependencies individually.
 
2. Start services FlowCept depends on: MongoDB and Redis

The easiest way to start FlowCept services is by using its [docker-compose file](deployment/compose.yml) for its dependent services: 
MongoDB and Redis. You only need RabbitMQ if you want to observe Zambeze messages as well.

3. Define the settings (e.g., routes and ports) accordingly in the [settings.yaml](resources/settings.yaml) file.

4. Start the observation using the Controller API, as shown in the [Jupyter Notebooks](notebooks).

5. To use FlowCept's Query API, you need to start the flask webserver:
`python flowcept/flowcept_webserver/app.py`. Query API utilization examples are 
available in the notebooks.


## Performance Tuning for Performance Evaluation

In the settings.yaml file, the following variables might impact interception performance:

```yaml
main_redis:
  buffer_size: 50
  insertion_buffer_time_secs: 5

plugin:
  enrich_messages: false
```

And other variables depending on the Plugin. For instance, in Dask, timestamp creation by workers add interception overhead.


# Plugins-specific info

You can run `pip install flowcept[plugin_name]` to install requirements for a specific plugin, instead of installing the
whole package.

### RabbitMQ for Zambeze plugin
```bash
$ docker run -it --rm --name rabbitmq -d -p 5672:5672 -p 15672:15672 rabbitmq:3.11-management
```

### Tensorboard

If you're on mac, `pip install` may not work out of the box because of Tensorflow library. 
You may need to `pip install tensorflow-macos` instead of the `tensorflow` lib available in the tensorboard-requirements.


# See also

- [Zambeze Repository](https://github.com/ORNL/zambeze)