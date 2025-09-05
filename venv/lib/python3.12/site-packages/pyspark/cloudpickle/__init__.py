# BEGIN-EDGE
from pyspark._engine_adapters import IS_ENGINE_PYSPARK

if IS_ENGINE_PYSPARK:
    assert False, "Cloudpickle should not be imported in _engine_pyspark instead the client cloudpickle module should be used"
# END-EDGE


from pyspark.cloudpickle import cloudpickle  # noqa
from pyspark.cloudpickle.cloudpickle import *  # noqa

__doc__ = cloudpickle.__doc__

__version__ = "3.1.1"

__all__ = [  # noqa
    "__version__",
    "Pickler",
    "CloudPickler",
    "dumps",
    "loads",
    "dump",
    "load",
    "register_pickle_by_value",
    "unregister_pickle_by_value",
]
