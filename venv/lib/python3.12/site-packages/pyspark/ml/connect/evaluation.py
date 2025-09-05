#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from typing import Any, Union, List, Tuple

from contextlib import contextmanager
import numpy as np
import pandas as pd

from pyspark import keyword_only
from pyspark import cloudpickle
from pyspark.ml.param import Param, Params, TypeConverters
from pyspark.ml.param.shared import HasLabelCol, HasPredictionCol, HasProbabilityCol
from pyspark.ml.connect.base import Evaluator
from pyspark.ml.connect.io_utils import ParamsReadWrite
from pyspark.sql import DataFrame


@contextmanager
def _disable_torch_jit():
    import torch

    origin_state = torch.jit._state._enabled.enabled
    torch.jit._state.disable()
    yield
    if origin_state:
        torch.jit._state.enable()


class _TorchMetricEvaluator(Evaluator):
    metricName: Param[str] = Param(
        Params._dummy(),
        "metricName",
        "metric name for the regression evaluator, valid values are 'mse' and 'r2'",
        typeConverter=TypeConverters.toString,
    )

    def getMetricName(self) -> str:
        """
        Gets the value of metricName or its default value.

        .. versionadded:: 3.5.0

        .. deprecated:: 4.0.0
        """
        return self.getOrDefault(self.metricName)

    def _get_torch_metric(self) -> Any:
        raise NotImplementedError()

    def _get_input_cols(self) -> List[str]:
        raise NotImplementedError()

    def _get_metric_update_inputs(self, dataset: "pd.DataFrame") -> Tuple[Any, Any]:
        raise NotImplementedError()

    def _evaluate(self, dataset: Union["DataFrame", "pd.DataFrame"]) -> float:
        from pyspark.ml.connect.util import aggregate_dataframe

        with _disable_torch_jit():
            torch_metric = self._get_torch_metric()
            init_state_ser = cloudpickle.dumps(torch_metric)

            def local_agg_fn(pandas_df: "pd.DataFrame") -> Any:
                with _disable_torch_jit():
                    state = cloudpickle.loads(init_state_ser)
                    state.update(*self._get_metric_update_inputs(pandas_df))
                    return cloudpickle.dumps(state)

            def merge_agg_state(state1_ser: Any, state2_ser: Any) -> Any:
                with _disable_torch_jit():
                    state1 = cloudpickle.loads(state1_ser)
                    state2 = cloudpickle.loads(state2_ser)
                    state1.merge_state([state2])
                    return cloudpickle.dumps(state1)

            def agg_state_to_result(state_ser: Any) -> Any:
                with _disable_torch_jit():
                    state = cloudpickle.loads(state_ser)
                    return state.compute().item()

            return aggregate_dataframe(
                dataset,
                self._get_input_cols(),
                local_agg_fn,
                merge_agg_state,
                agg_state_to_result,
            )


def _get_rmse_torchmetric() -> Any:
    import torch
    import torcheval.metrics as torchmetrics

    class _RootMeanSquaredError(torchmetrics.MeanSquaredError):
        def compute(self: Any) -> torch.Tensor:
            return torch.sqrt(super().compute())

    return _RootMeanSquaredError()


class RegressionEvaluator(_TorchMetricEvaluator, HasLabelCol, HasPredictionCol, ParamsReadWrite):
    """
    Evaluator for Regression, which expects input columns prediction and label.
    Supported metrics are 'rmse', 'mse' and 'r2'.

    .. versionadded:: 3.5.0

    .. deprecated:: 4.0.0

    Examples
    --------
    >>> from pyspark.ml.connect.evaluation import RegressionEvaluator
    >>> eva = RegressionEvaluator(metricName='mse')
    >>> dataset = spark.createDataFrame(
    ...     [(1.0, 2.0), (-1.0, -1.5)], schema=['label', 'prediction']
    ... )
    >>> eva.evaluate(dataset)
    0.625
    >>> eva.isLargerBetter()
    False
    """

    @keyword_only
    def __init__(
        self,
        *,
        metricName: str = "rmse",
        labelCol: str = "label",
        predictionCol: str = "prediction",
    ) -> None:
        """
        __init__(self, *, metricName='rmse', labelCol='label', predictionCol='prediction') -> None:
        """
        super().__init__()
        self._set(metricName=metricName, labelCol=labelCol, predictionCol=predictionCol)

    def _get_torch_metric(self) -> Any:
        import torcheval.metrics as torchmetrics

        metric_name = self.getOrDefault(self.metricName)

        if metric_name == "mse":
            return torchmetrics.MeanSquaredError()
        if metric_name == "r2":
            return torchmetrics.R2Score()
        if metric_name == "rmse":
            return _get_rmse_torchmetric()

        raise ValueError(f"Unsupported regressor evaluator metric name: {metric_name}")

    def _get_input_cols(self) -> List[str]:
        return [self.getPredictionCol(), self.getLabelCol()]

    def _get_metric_update_inputs(self, dataset: "pd.DataFrame") -> Tuple[Any, Any]:
        import torch

        preds_tensor = torch.tensor(dataset[self.getPredictionCol()].values)
        labels_tensor = torch.tensor(dataset[self.getLabelCol()].values)
        return preds_tensor, labels_tensor

    def isLargerBetter(self) -> bool:
        if self.getOrDefault(self.metricName) == "r2":
            return True

        return False


class BinaryClassificationEvaluator(
    _TorchMetricEvaluator, HasLabelCol, HasProbabilityCol, ParamsReadWrite
):
    """
    Evaluator for binary classification, which expects input columns prediction and label.
    Supported metrics are 'areaUnderROC' and 'areaUnderPR'.

    .. versionadded:: 3.5.0

    .. deprecated:: 4.0.0

    Examples
    --------
    >>> from pyspark.ml.connect.evaluation import BinaryClassificationEvaluator
    >>> eva = BinaryClassificationEvaluator(metricName='areaUnderPR')
    >>> dataset = spark.createDataFrame(
    ...     [(1, 0.6), (0, 0.55), (0, 0.1), (1, 0.6), (1, 0.4)],
    ...     schema=['label', 'probability']
    ... )
    >>> eva.evaluate(dataset)
    0.9166666865348816
    >>> eva.isLargerBetter()
    True
    """

    @keyword_only
    def __init__(
        self,
        *,
        metricName: str = "areaUnderROC",
        labelCol: str = "label",
        probabilityCol: str = "probability",
    ) -> None:
        """
        __init__(
            self,
            *,
            metricName='rmse',
            labelCol='label',
            probabilityCol='probability'
        ) -> None:
        """
        super().__init__()
        self._set(metricName=metricName, labelCol=labelCol, probabilityCol=probabilityCol)

    def _get_torch_metric(self) -> Any:
        import torcheval.metrics as torchmetrics

        metric_name = self.getOrDefault(self.metricName)

        if metric_name == "areaUnderROC":
            return torchmetrics.BinaryAUROC()
        if metric_name == "areaUnderPR":
            return torchmetrics.BinaryAUPRC()

        raise ValueError(f"Unsupported binary classification evaluator metric name: {metric_name}")

    def _get_input_cols(self) -> List[str]:
        return [self.getProbabilityCol(), self.getLabelCol()]

    def _get_metric_update_inputs(self, dataset: "pd.DataFrame") -> Tuple[Any, Any]:
        import torch

        values = np.stack(dataset[self.getProbabilityCol()].values)  # type: ignore[call-overload]
        preds_tensor = torch.tensor(values)
        if preds_tensor.dim() == 2:
            preds_tensor = preds_tensor[:, 1]
        labels_tensor = torch.tensor(dataset[self.getLabelCol()].values)
        return preds_tensor, labels_tensor

    def isLargerBetter(self) -> bool:
        return True


class MulticlassClassificationEvaluator(
    _TorchMetricEvaluator, HasLabelCol, HasPredictionCol, ParamsReadWrite
):
    """
    Evaluator for multiclass classification, which expects input columns prediction and label.
    Supported metrics are 'accuracy'.

    .. versionadded:: 3.5.0

    .. deprecated:: 4.0.0

    Examples
    --------
    >>> from pyspark.ml.connect.evaluation import MulticlassClassificationEvaluator
    >>> eva = MulticlassClassificationEvaluator(metricName='accuracy')
    >>> dataset = spark.createDataFrame(
    ...     [(1, 1), (0, 0), (2, 2), (1, 0), (2, 1)],
    ...     schema=['label', 'prediction']
    ... )
    >>> eva.evaluate(dataset)
    0.6000000238418579
    >>> eva.isLargerBetter()
    True
    """

    def __init__(
        self,
        metricName: str = "accuracy",
        labelCol: str = "label",
        predictionCol: str = "prediction",
    ) -> None:
        """
        __init__(
            self,
            *,
            metricName='accuracy',
            labelCol='label',
            predictionCol='prediction'
        ) -> None:
        """
        super().__init__()
        self._set(metricName=metricName, labelCol=labelCol, predictionCol=predictionCol)

    def _get_torch_metric(self) -> Any:
        import torcheval.metrics as torchmetrics

        metric_name = self.getOrDefault(self.metricName)

        if metric_name == "accuracy":
            return torchmetrics.MulticlassAccuracy()

        raise ValueError(
            f"Unsupported multiclass classification evaluator metric name: {metric_name}"
        )

    def _get_input_cols(self) -> List[str]:
        return [self.getPredictionCol(), self.getLabelCol()]

    def _get_metric_update_inputs(self, dataset: "pd.DataFrame") -> Tuple[Any, Any]:
        import torch

        preds_tensor = torch.tensor(dataset[self.getPredictionCol()].values)
        labels_tensor = torch.tensor(dataset[self.getLabelCol()].values)
        return preds_tensor, labels_tensor

    def isLargerBetter(self) -> bool:
        return True
