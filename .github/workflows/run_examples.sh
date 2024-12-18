#!/bin/bash

# Exit immediately on non-zero exit status and propagate errors in pipelines
set -e
set -o pipefail

# Display usage/help message
usage() {
  echo -e "\nUsage: $0 <examples_dir> <with_mongo>\n"
  echo "Arguments:"
  echo "  examples_dir   Path to the examples directory (Mandatory)"
  echo "  with_mongo     Boolean flag (true/false) indicating whether to include MongoDB support (Mandatory)"
  echo -e "\nExample:"
  echo "  $0 examples true"
  echo "  $0 examples false"
  exit 1
}

# Check if the required arguments are provided
if [[ -z "$1" || -z "$2" ]]; then
  echo "Error: Missing mandatory arguments!"
  usage
fi

# Function to run tests with common steps
run_test() {
  test_path="${EXAMPLES_DIR}/${1}_example.py"
  test_type="$1"
  with_mongo="$2"
  echo "Test type=${test_type}"
  echo "Starting $test_path"

  pip uninstall flowcept -y > /dev/null 2>&1 || true  # Ignore errors during uninstall

  pip install . > /dev/null 2>&1

  if [[ "$with_mongo" == "true" ]]; then
    pip install .[mongo] > /dev/null 2>&1
  fi

  if [[ "$test_type" =~ "mlflow" ]]; then
    echo "Installing mlflow"
    pip install .[mlflow] > /dev/null 2>&1
  elif [[ "$test_type" =~ "dask" ]]; then
    echo "Installing dask"
    pip install .[dask] > /dev/null 2>&1
  elif [[ "$test_type" =~ "tensorboard" ]]; then
    echo "Installing tensorboard"
    pip install .[tensorboard] > /dev/null 2>&1
  elif [[ "$test_type" =~ "single_layer_perceptron" ]]; then
    echo "Installing ml_dev dependencies"
    pip install .[ml_dev] > /dev/null 2>&1
  elif [[ "$test_type" =~ "llm_complex" ]]; then
    echo "Installing ml_dev dependencies"
    pip install .[ml_dev]
    echo "Defining python path for llm_complex..."
    export PYTHONPATH=$PYTHONPATH:${EXAMPLES_DIR}/llm_complex
    echo $PYTHONPATH
  fi

  echo "Running $test_path ..."
  python "$test_path" | tee output.log
  echo "Ok, ran $test_path."
  # Check for errors in the output
  if grep -iq "error" output.log; then
    echo "Test $test_path failed! See output.log for details."
    exit 1
  fi

  echo "Great, no errors to run $test_path."

  # Clean up the log file
  rm output.log
}

# Get the examples directory as the first argument
EXAMPLES_DIR="$1"
WITH_MONGO="$2"
echo "Using examples directory: $EXAMPLES_DIR"
echo "With Mongo? ${WITH_MONGO}"

# Define the test cases
tests=("instrumented_simple" "instrumented_loop" "dask" "mlflow" "tensorboard" "single_layer_perceptron" "llm_complex/llm_main")

# Iterate over the tests and run them
for test_ in "${tests[@]}"; do
  run_test $test_ $WITH_MONGO
done

echo "Tests completed successfully!"
