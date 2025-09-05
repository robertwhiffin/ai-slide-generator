import os
import zipfile


def check_class_exists(class_name):
    env = dict(os.environ)
    spark_classpath = env["SPARK_DIST_CLASSPATH"]
    assembly_jar = zipfile.ZipFile(spark_classpath, "r")
    for filepath in assembly_jar.namelist():
        if class_name in filepath:
            return True
    return False
