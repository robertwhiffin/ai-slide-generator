#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from collections import namedtuple
import numpy as np

from pyspark import keyword_only
from pyspark.ml import Estimator, Model, Transformer, UnaryTransformer
from pyspark.ml.evaluation import Evaluator
from pyspark.ml.param import Param, Params, TypeConverters
from pyspark.ml.param.shared import HasMaxIter, HasRegParam
from pyspark.ml.classification import Classifier, ClassificationModel
from pyspark.ml.util import DefaultParamsReadable, DefaultParamsWritable
from pyspark.ml.wrapper import _java2py
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import DoubleType
from pyspark.testing.utils import ReusedPySparkTestCase as PySparkTestCase


def check_params(test_self, py_stage, check_params_exist=True):
    """
    Checks common requirements for :py:class:`PySpark.ml.Params.params`:

      - set of params exist in Java and Python and are ordered by names
      - param parent has the same UID as the object's UID
      - default param value from Java matches value in Python
      - optionally check if all params from Java also exist in Python
    """
    py_stage_str = "%s %s" % (type(py_stage), py_stage)
    if not hasattr(py_stage, "_to_java"):
        return
    java_stage = py_stage._to_java()
    if java_stage is None:
        return
    test_self.assertEqual(py_stage.uid, java_stage.uid(), msg=py_stage_str)
    if check_params_exist:
        param_names = [p.name for p in py_stage.params]
        java_params = list(java_stage.params())
        java_param_names = [jp.name() for jp in java_params]
        test_self.assertEqual(
            param_names,
            sorted(java_param_names),
            "Param list in Python does not match Java for %s:\nJava = %s\nPython = %s"
            % (py_stage_str, java_param_names, param_names),
        )
    for p in py_stage.params:
        test_self.assertEqual(p.parent, py_stage.uid)
        java_param = java_stage.getParam(p.name)
        py_has_default = py_stage.hasDefault(p)
        java_has_default = java_stage.hasDefault(java_param)
        test_self.assertEqual(
            py_has_default,
            java_has_default,
            "Default value mismatch of param %s for Params %s" % (p.name, str(py_stage)),
        )
        if py_has_default:
            if p.name == "seed":
                continue  # Random seeds between Spark and PySpark are different
            java_default = _java2py(
                test_self.sc, java_stage.clear(java_param).getOrDefault(java_param)
            )
            py_stage.clear(p)
            py_default = py_stage.getOrDefault(p)
            # equality test for NaN is always False
            if isinstance(java_default, float) and np.isnan(java_default):
                java_default = "NaN"
                py_default = "NaN" if np.isnan(py_default) else "not NaN"
            test_self.assertEqual(
                java_default,
                py_default,
                "Java default %s != python default %s of param %s for Params %s"
                % (str(java_default), str(py_default), p.name, str(py_stage)),
            )


class SparkSessionTestCase(PySparkTestCase):
    @classmethod
    def setUpClass(cls):
        PySparkTestCase.setUpClass()
        cls.spark = SparkSession(cls.sc)

    @classmethod
    def tearDownClass(cls):
        PySparkTestCase.tearDownClass()
        cls.spark.stop()


class MockDataset(DataFrame):
    def __new__(cls) -> "DataFrame":
        self = object.__new__(cls)
        self.__init__()
        return self

    def __init__(self):
        self.index = 0


class HasFake(Params):
    def __init__(self):
        super(HasFake, self).__init__()
        self.fake = Param(self, "fake", "fake param")

    def getFake(self):
        return self.getOrDefault(self.fake)


class MockTransformer(Transformer, HasFake):
    def __init__(self):
        super(MockTransformer, self).__init__()
        self.dataset_index = None

    def _transform(self, dataset):
        self.dataset_index = dataset.index
        dataset.index += 1
        return dataset


class MockUnaryTransformer(UnaryTransformer, DefaultParamsReadable, DefaultParamsWritable):
    shift = Param(
        Params._dummy(),
        "shift",
        "The amount by which to shift " + "data in a DataFrame",
        typeConverter=TypeConverters.toFloat,
    )

    def __init__(self, shiftVal=1):
        super(MockUnaryTransformer, self).__init__()
        self._setDefault(shift=1)
        self._set(shift=shiftVal)

    def getShift(self):
        return self.getOrDefault(self.shift)

    def setShift(self, shift):
        self._set(shift=shift)

    def createTransformFunc(self):
        shiftVal = self.getShift()
        return lambda x: x + shiftVal

    def outputDataType(self):
        return DoubleType()

    def validateInputType(self, inputType):
        if inputType != DoubleType():
            raise TypeError("Bad input type: {}. ".format(inputType) + "Requires Double.")


class MockEstimator(Estimator, HasFake):
    def __init__(self):
        super(MockEstimator, self).__init__()
        self.dataset_index = None

    def _fit(self, dataset):
        self.dataset_index = dataset.index
        model = MockModel()
        self._copyValues(model)
        return model


class MockModel(MockTransformer, Model, HasFake):
    pass


# Note: In MLflow 0.9 and earlier, RunInfo had field 'run_uuid'.
# In MLflow 1.0+, 'run_uuid' exists but has been deprecated in favor of 'run_id'.
MockRunInfo = namedtuple("MockRunInfo", ["run_uuid", "status"])
MockRunData = namedtuple("MockRunInfo", ["params", "metrics", "tags"])
_active_run_stack = []
_run_history = []


class MockRun:
    """
    Mock for mlflow.entities.Run.
    When an instance is created, it adds itself to _run_history
    """

    def __init__(self, run_info=None, run_data=None):
        global _run_history
        if run_info is None:
            run_uuid = len(_run_history)
            run_info = MockRunInfo(run_uuid=run_uuid, status="RUNNING")
        self.info = run_info
        if run_data is None:
            run_data = MockRunData(params={}, metrics={}, tags={})
        self.data = run_data
        _run_history.append(self)


class MockActiveRun(MockRun):
    """
    Wrapper class to enable ``with`` syntax like a contextmanager
    """

    def __init__(self):
        MockRun.__init__(self)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        MockMLflow.end_run()


class MockMLflowTracking:
    """
    Mock for mlflow.tracking module
    """

    fake_uri = "MY_FAKE_URI"

    @staticmethod
    def get_tracking_uri():
        return MockMLflowTracking.fake_uri


class MockMLflow:
    """
    Mock class for MLflow fluent/stateful API
    """

    # Mock for mlflow.tracking
    tracking = MockMLflowTracking

    @staticmethod
    def start_run(nested=False, experiment_id=None):
        # MLflow 1.0.0 in Databricks defaults to an invalid experiment id 0.
        # This fails if the current experiment ID is 0.
        exp_id_for_run = (
            experiment_id if experiment_id is not None else MockMLflowUtil._get_experiment_id()
        )
        assert exp_id_for_run != 0, (
            "MockMLflow.start_run found invalid experiment_id 0. "
            "You probably need to set the experiment ID explicitly."
        )

        global _active_run_stack
        parent_active_run = MockMLflow.active_run()
        run = MockActiveRun()
        if parent_active_run:
            assert nested, (
                "MockMLflow.start_run(nested) was called with nested=False when there "
                "was already an active run, which is invalid usage."
            )
            run.data.tags["mlflow.parentRunId"] = parent_active_run.info.run_uuid
        _active_run_stack.append(run)
        return _active_run_stack[-1]

    @staticmethod
    def end_run():
        global _active_run_stack
        if _active_run_stack:
            ended_run = _active_run_stack.pop()
        # Set the run's status to `FINISHED` upon termination
        ended_run.info = MockRunInfo(run_uuid=ended_run.info.run_uuid, status="FINISHED")

    @staticmethod
    def active_run():
        """Get the currently active ``Run``, or None if no such run exists."""
        global _active_run_stack
        return _active_run_stack[-1] if len(_active_run_stack) > 0 else None

    @staticmethod
    def _get_or_start_run():
        global _active_run_stack
        if len(_active_run_stack) == 0:
            MockMLflow.start_run()
        return _active_run_stack[-1]

    @staticmethod
    def log_param(name, value):
        global _run_history
        active_run = MockMLflow._get_or_start_run()
        active_run.data.params[name] = value

    @staticmethod
    def log_metric(name, value):
        global _run_history
        active_run = MockMLflow._get_or_start_run()
        active_run.data.metrics[name] = value

    @staticmethod
    def set_tag(name, value):
        global _run_history
        active_run = MockMLflow._get_or_start_run()
        active_run.data.tags[name] = value


class MockMLflowUtil:
    """
    Helper class to check the logging by the mock MockMLflow and MockMlflowClient class
    """

    default_experiment_id = 1

    @staticmethod
    def _get_experiment_id():
        return MockMLflowUtil.default_experiment_id

    @staticmethod
    def cleanup_tests():
        global _active_run_stack
        global _run_history
        _active_run_stack = []
        _run_history = []

    @staticmethod
    def get_num_params():
        global _run_history
        num_params = 0
        for run in _run_history:
            num_params = num_params + len(run.data.params)
        return num_params

    @staticmethod
    def get_num_params_for_run(run_uuid):
        global _run_history
        return len(_run_history[run_uuid].data.params)

    @staticmethod
    def get_num_metrics():
        global _run_history
        num_metrics = 0
        for run in _run_history:
            num_metrics = num_metrics + len(run.data.metrics)
        return num_metrics

    @staticmethod
    def get_num_tags():
        global _run_history
        num_tag = 0
        for run in _run_history:
            num_tag = num_tag + len(run.data.tags)
        return num_tag

    @staticmethod
    def get_num_runs():
        global _run_history
        return len(_run_history)

    @staticmethod
    def get_param(run_uuid, name):
        global _run_history
        if name in _run_history[run_uuid].data.params:
            return _run_history[run_uuid].data.params[name]
        else:
            return None

    @staticmethod
    def get_metric(run_uuid, name):
        global _run_history
        if name in _run_history[run_uuid].data.metrics:
            return _run_history[run_uuid].data.metrics[name]
        else:
            return None

    @staticmethod
    def get_tag(run_uuid, name):
        global _run_history
        if name in _run_history[run_uuid].data.tags:
            return _run_history[run_uuid].data.tags[name]
        else:
            return None

    @staticmethod
    def get_run_list(filter=None):
        """
        Get list of all runs, with optional filters
        :param filter: Function applied to Run which returns True if the run should be
                       included in the returned list.
        """
        global _run_history
        if filter is None:
            return _run_history
        return [r for r in _run_history if filter(r)]


class MockMlflowClient:
    # Set this to True to mimic an unreachable server
    disable_server = False

    """
    Mock for MLflow client interface
    """

    @staticmethod
    def create_run(experiment_id, tags={}):
        data = MockRunData(params={}, metrics={}, tags=tags)
        return MockRun(run_data=data)

    @staticmethod
    def log_param(run_uuid, name, value):
        global _run_history
        run = _run_history[run_uuid]
        run.data.params[name] = value

    @staticmethod
    def log_metric(run_uuid, name, value):
        global _run_history
        run = _run_history[run_uuid]
        run.data.metrics[name] = value

    @staticmethod
    def set_tag(run_uuid, name, value):
        global _run_history
        run = _run_history[run_uuid]
        run.data.tags[name] = value

    def get_experiment_by_name(self, name):
        """In MLflow, this returns a mlflow.entities.Experiment instance"""
        if MockMlflowClient.disable_server:
            raise Exception()
        return None

    def get_run(self, run_id):
        """In MLflow, this returns a mlflow.entities.Run instance"""
        global _run_history
        matching_runs = [r for r in _run_history if r.info.run_uuid == run_id]
        assert (
            len(matching_runs) == 1
        ), "MockMlflowClient.get_run(run_id={run_id}) found {n} runs matching this run ID".format(
            run_id=run_id, n=len(matching_runs)
        )
        return matching_runs[0]

    def set_terminated(self, run_id, status, end_time=None):
        global _run_history
        run = _run_history[run_id]
        run.info = MockRunInfo(run_uuid=run.info.run_uuid, status=status)


class _DummyLogisticRegressionParams(HasMaxIter, HasRegParam):
    def setMaxIter(self, value):
        return self._set(maxIter=value)

    def setRegParam(self, value):
        return self._set(regParam=value)


# This is a dummy LogisticRegression used in test for python backend estimator/model
class DummyLogisticRegression(
    Classifier, _DummyLogisticRegressionParams, DefaultParamsReadable, DefaultParamsWritable
):
    @keyword_only
    def __init__(
        self,
        *,
        featuresCol="features",
        labelCol="label",
        predictionCol="prediction",
        maxIter=100,
        regParam=0.0,
        rawPredictionCol="rawPrediction",
    ):
        super(DummyLogisticRegression, self).__init__()
        kwargs = self._input_kwargs
        self.setParams(**kwargs)

    @keyword_only
    def setParams(
        self,
        *,
        featuresCol="features",
        labelCol="label",
        predictionCol="prediction",
        maxIter=100,
        regParam=0.0,
        rawPredictionCol="rawPrediction",
    ):
        kwargs = self._input_kwargs
        self._set(**kwargs)
        return self

    def _fit(self, dataset):
        # Do nothing but create a dummy model
        return self._copyValues(DummyLogisticRegressionModel())


class DummyLogisticRegressionModel(
    ClassificationModel,
    _DummyLogisticRegressionParams,
    DefaultParamsReadable,
    DefaultParamsWritable,
):
    def __init__(self):
        super(DummyLogisticRegressionModel, self).__init__()

    def _transform(self, dataset):
        # A dummy transform impl which always predict label 1
        from pyspark.sql.functions import array, lit
        from pyspark.ml.functions import array_to_vector

        rawPredCol = self.getRawPredictionCol()
        if rawPredCol:
            dataset = dataset.withColumn(
                rawPredCol, array_to_vector(array(lit(-100.0), lit(100.0)))
            )
        predCol = self.getPredictionCol()
        if predCol:
            dataset = dataset.withColumn(predCol, lit(1.0))

        return dataset

    @property
    def numClasses(self):
        # a dummy implementation for test.
        return 2

    @property
    def intercept(self):
        # a dummy implementation for test.
        return 0.0

    # This class only used in test. The following methods/properties are not used in tests.

    @property
    def coefficients(self):
        raise NotImplementedError()

    def predictRaw(self, value):
        raise NotImplementedError()

    def numFeatures(self):
        raise NotImplementedError()

    def predict(self, value):
        raise NotImplementedError()


class DummyEvaluator(Evaluator, DefaultParamsReadable, DefaultParamsWritable):
    def _evaluate(self, dataset):
        # a dummy implementation for test.
        return 1.0
