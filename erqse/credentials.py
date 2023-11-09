import os
from environs import Env
import json


def get_credentials(env_variable_name="ERCOT_CREDENTIALS", file_and_path_to_dot_env=".env", recurse=True):
    """
    Returns credentials based on an environment variable or specified environment file
    :param env_variable_name: requested environment variable name
    :param file_and_path_to_dot_env:
    :param recurse:
    :return: dictionary of database credentials
    """

    env = Env()

    if env_variable_name in os.environ:
        return json.loads(env.str(env_variable_name))

    file_and_path_formatted = os.path.abspath(file_and_path_to_dot_env)
    env.read_env(file_and_path_formatted, recurse=recurse)
    return json.loads(env.str(env_variable_name))
