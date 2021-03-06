import os
import unittest

import mock

from pulp.server import config
from pulp.server.db import connection
from pulp.server.logs import start_logging, stop_logging


class _ConfigAlteredDuringTestingError(RuntimeError):
    """Exception raised during attempts to modify the pulp config during unit testing"""


def drop_database():
    """
    Drop the database so that the next test run starts with a clean database.
    """
    connection._CONNECTION.drop_database(connection._DATABASE.name)


def start_database_connection():
    """
    Start the database connection, if it is not already established.
    """
    # It's important to only call this once during the process
    if not connection._CONNECTION:
        _load_test_config()
        connection.initialize()


def _enforce_config(wrapped_func_name):
    """
    Raise an Exception that tells developers to mock the config rather than trying to change the
    real config.

    :param wrapped_func_name: Name of function being replaced by the config enforcer
    :type  str :

    :raises:       Exception
    """
    def the_enforcer(*args, **kwargs):
        raise _ConfigAlteredDuringTestingError(
            "Attempt to modify the config during a test run has been blocked. "
            "{0} was called with args {1} and kwargs {2}".format(
                wrapped_func_name, args, kwargs))
    return the_enforcer


def _load_test_config():
    """
    Load test configuration, reconfigure logging, block config changes during testing
    """
    # prevent reading of server.conf
    block_load_conf()

    # allow altering the conf during config load, since we have to load the defaults
    restore_config_attrs()

    # force reloading the config
    config.load_configuration()

    # configure the test database
    config.config.set('database', 'name', 'pulp_unittest')
    config.config.set('server', 'storage_dir', '/tmp/pulp')

    # reset logging conf
    stop_logging()
    start_logging()

    # block future attempts to alter the config in place
    override_config_attrs()


def override_config_attrs():
    if not hasattr(config, '_overridden_attrs'):
        # only save these once so we don't end up saving _enforce_config as the "original" values
        setattr(config, '_overridden_attrs', {
            '__setattr__': config.__setattr__,
            'load_configuration': config.load_configuration,
            'config.set': config.config.set,
        })

    # Prevent the tests from altering the config so that nobody accidentally makes global changes
    config.__setattr__ = _enforce_config(
        '.'.join((config.__package__, 'config.__setattr__')))
    config.load_configuration = _enforce_config(
        '.'.join((config.__package__, 'config.load_configuration')))
    config.config.set = _enforce_config(
        '.'.join((config.__package__, 'config.config.set')))


def restore_config_attrs():
    # Restore values overridden by _override_config_attrs
    if not hasattr(config, '_overridden_attrs'):
        return

    for attr in '__setattr__', 'load_configuration':
        setattr(config, attr, config._overridden_attrs[attr])
    config.config.set = config._overridden_attrs['config.set']


def block_load_conf():
    # Remove server.conf from the list of autoloaded config files
    # This is needed when testing modules that create objects using conf data found in the
    # server config, such as DB connections, celery, etc. This should be used as little as
    # possible and as early as possible, before config file loads happen
    try:
        config.remove_config_file('/etc/pulp/server.conf')
    except RuntimeError:
        # server.conf already removed, move along...
        pass


class PulpWebservicesTests(unittest.TestCase):
    """
    Base class for tests of webservice controllers.  This base is used to work around the
    authentication tests for each each method
    """

    def setUp(self):
        self.patch1 = mock.patch('pulp.server.webservices.views.decorators.'
                                 'check_preauthenticated')
        self.patch2 = mock.patch('pulp.server.webservices.views.decorators.'
                                 'is_consumer_authorized')
        self.patch3 = mock.patch('pulp.server.webservices.http.resource_path')
        self.patch4 = mock.patch('web.webapi.HTTPError')
        self.patch5 = mock.patch('pulp.server.managers.factory.principal_manager')
        self.patch6 = mock.patch('pulp.server.managers.factory.user_query_manager')

        self.patch7 = mock.patch('pulp.server.webservices.http.uri_path')
        self.mock_check_pre_auth = self.patch1.start()
        self.mock_check_pre_auth.return_value = 'ws-user'
        self.mock_check_auth = self.patch2.start()
        self.mock_check_auth.return_value = True
        self.mock_http_resource_path = self.patch3.start()
        self.patch4.start()
        self.patch5.start()
        self.mock_user_query_manager = self.patch6.start()
        self.mock_user_query_manager.return_value.is_superuser.return_value = False
        self.mock_user_query_manager.return_value.is_authorized.return_value = True
        self.mock_uri_path = self.patch7.start()
        self.mock_uri_path.return_value = "/mock/"

    def tearDown(self):
        self.patch1.stop()
        self.patch2.stop()
        self.patch3.stop()
        self.patch4.stop()
        self.patch5.stop()
        self.patch6.stop()
        self.patch7.stop()

    def validate_auth(self, operation):
        """
        validate that a validation check was performed for a given operation
        :param operation: the operation to validate
        """
        self.mock_user_query_manager.return_value.is_authorized.assert_called_once_with(
            mock.ANY, mock.ANY, operation)

    def get_mock_uri_path(self, *args):
        """
        :param object_id: the id of the object to get the uri for
        :type object_id: str
        """
        return os.path.join('/mock', *args) + '/'
