# Copyright 2015 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import datetime
from unittest import mock

from oslo_config import cfg
from oslo_config import fixture as oslo_fixture
from oslo_utils import uuidutils

from octavia.common import constants
from octavia.controller.housekeeping import house_keeping
from octavia.db import repositories as repo
import octavia.tests.unit.base as base


CONF = cfg.CONF
AMPHORA_ID = uuidutils.generate_uuid()


class TestException(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class TestDatabaseCleanup(base.TestCase):
    FAKE_IP = "10.0.0.1"
    FAKE_UUID_1 = uuidutils.generate_uuid()
    FAKE_UUID_2 = uuidutils.generate_uuid()
    FAKE_EXP_AGE = 60

    def setUp(self):
        super().setUp()
        self.dbclean = house_keeping.DatabaseCleanup()
        self.amp_health_repo = mock.MagicMock()
        self.amp_repo = mock.MagicMock()
        self.amp = repo.AmphoraRepository()
        self.lb = repo.LoadBalancerRepository()

        self.dbclean.amp_repo = self.amp_repo
        self.dbclean.amp_health_repo = self.amp_health_repo
        self.CONF = self.useFixture(oslo_fixture.Config(cfg.CONF))

    @mock.patch('octavia.db.api.get_session')
    def test_delete_old_amphorae_True(self, session):
        """When the deleted amphorae is expired."""
        session.return_value = session
        self.CONF.config(group="house_keeping",
                         amphora_expiry_age=self.FAKE_EXP_AGE)
        expired_time = datetime.datetime.utcnow() - datetime.timedelta(
            seconds=self.FAKE_EXP_AGE + 1)
        amphora = self.amp.create(session, id=self.FAKE_UUID_1,
                                  compute_id=self.FAKE_UUID_2,
                                  status=constants.DELETED,
                                  lb_network_ip=self.FAKE_IP,
                                  vrrp_ip=self.FAKE_IP,
                                  ha_ip=self.FAKE_IP,
                                  updated_at=expired_time)
        self.amp_repo.get_all_deleted_expiring.return_value = [amphora.id]
        self.amp_health_repo.check_amphora_health_expired.return_value = True
        self.dbclean.delete_old_amphorae()
        self.assertTrue(self.amp_repo.get_all_deleted_expiring.called)
        self.assertTrue(
            self.amp_health_repo.check_amphora_health_expired.called)
        self.assertTrue(self.amp_repo.delete.called)

    @mock.patch('octavia.db.api.get_session')
    def test_delete_old_amphorae_False(self, session):
        """When the deleted amphorae is not expired."""
        session.return_value = session
        self.CONF.config(group="house_keeping",
                         amphora_expiry_age=self.FAKE_EXP_AGE)
        self.amp.create(session, id=self.FAKE_UUID_1,
                        compute_id=self.FAKE_UUID_2,
                        status=constants.DELETED,
                        lb_network_ip=self.FAKE_IP,
                        vrrp_ip=self.FAKE_IP,
                        ha_ip=self.FAKE_IP,
                        updated_at=datetime.datetime.now())
        self.amp_repo.get_all_deleted_expiring.return_value = []
        self.dbclean.delete_old_amphorae()
        self.assertTrue(self.amp_repo.get_all_deleted_expiring.called)
        self.assertFalse(
            self.amp_health_repo.check_amphora_health_expired.called)
        self.assertFalse(self.amp_repo.delete.called)

    @mock.patch('octavia.db.api.get_session')
    def test_delete_old_amphorae_Zombie(self, session):
        """When the deleted amphorae is expired but is a zombie!

        This is when the amphora is expired in the amphora table, but in the
        amphora_health table there are newer records, meaning the amp checked
        in with the healthmanager *after* it was deleted (and craves brains).
        """
        session.return_value = session
        self.CONF.config(group="house_keeping",
                         amphora_expiry_age=self.FAKE_EXP_AGE)
        expired_time = datetime.datetime.utcnow() - datetime.timedelta(
            seconds=self.FAKE_EXP_AGE + 1)
        amphora = self.amp.create(session, id=self.FAKE_UUID_1,
                                  compute_id=self.FAKE_UUID_2,
                                  status=constants.DELETED,
                                  lb_network_ip=self.FAKE_IP,
                                  vrrp_ip=self.FAKE_IP,
                                  ha_ip=self.FAKE_IP,
                                  updated_at=expired_time)
        self.amp_repo.get_all_deleted_expiring.return_value = [amphora.id]
        self.amp_health_repo.check_amphora_health_expired.return_value = False
        self.dbclean.delete_old_amphorae()
        self.assertTrue(self.amp_repo.get_all_deleted_expiring.called)
        self.assertTrue(
            self.amp_health_repo.check_amphora_health_expired.called)
        self.assertFalse(self.amp_repo.delete.called)

    @mock.patch('octavia.db.api.get_session')
    def test_delete_old_load_balancer(self, session):
        """Check delete of load balancers in DELETED provisioning status."""
        self.CONF.config(group="house_keeping",
                         load_balancer_expiry_age=self.FAKE_EXP_AGE)
        session.return_value = session
        load_balancer = self.lb.create(session, id=self.FAKE_UUID_1,
                                       provisioning_status=constants.DELETED,
                                       operating_status=constants.OFFLINE,
                                       enabled=True)

        for expired_status in [True, False]:
            lb_repo = mock.MagicMock()
            self.dbclean.lb_repo = lb_repo
            if expired_status:
                expiring_lbs = [load_balancer.id]
            else:
                expiring_lbs = []
            lb_repo.get_all_deleted_expiring.return_value = expiring_lbs
            self.dbclean.cleanup_load_balancers()
            self.assertTrue(lb_repo.get_all_deleted_expiring.called)
            if expired_status:
                self.assertTrue(lb_repo.delete.called)
            else:
                self.assertFalse(lb_repo.delete.called)


class TestCertRotation(base.TestCase):
    def setUp(self):
        super().setUp()
        self.CONF = self.useFixture(oslo_fixture.Config(cfg.CONF))

    @mock.patch('octavia.controller.worker.v1.controller_worker.'
                'ControllerWorker.amphora_cert_rotation')
    @mock.patch('octavia.db.repositories.AmphoraRepository.'
                'get_cert_expiring_amphora')
    @mock.patch('octavia.db.api.get_session')
    def test_cert_rotation_expired_amphora_with_exception(self, session,
                                                          cert_exp_amp_mock,
                                                          amp_cert_mock
                                                          ):
        self.CONF.config(group="api_settings",
                         default_provider_driver='amphora')
        amphora = mock.MagicMock()
        amphora.id = AMPHORA_ID

        session.return_value = session
        cert_exp_amp_mock.side_effect = [amphora, TestException(
            'break_while')]

        cr = house_keeping.CertRotation()
        self.assertRaises(TestException, cr.rotate)
        amp_cert_mock.assert_called_once_with(AMPHORA_ID)

    @mock.patch('octavia.controller.worker.v1.controller_worker.'
                'ControllerWorker.amphora_cert_rotation')
    @mock.patch('octavia.db.repositories.AmphoraRepository.'
                'get_cert_expiring_amphora')
    @mock.patch('octavia.db.api.get_session')
    def test_cert_rotation_expired_amphora_without_exception(self, session,
                                                             cert_exp_amp_mock,
                                                             amp_cert_mock
                                                             ):
        self.CONF.config(group="api_settings",
                         default_provider_driver='amphora')
        amphora = mock.MagicMock()
        amphora.id = AMPHORA_ID

        session.return_value = session
        cert_exp_amp_mock.side_effect = [amphora, None]

        cr = house_keeping.CertRotation()

        self.assertIsNone(cr.rotate())
        amp_cert_mock.assert_called_once_with(AMPHORA_ID)

    @mock.patch('octavia.controller.worker.v1.controller_worker.'
                'ControllerWorker.amphora_cert_rotation')
    @mock.patch('octavia.db.repositories.AmphoraRepository.'
                'get_cert_expiring_amphora')
    @mock.patch('octavia.db.api.get_session')
    def test_cert_rotation_non_expired_amphora(self, session,
                                               cert_exp_amp_mock,
                                               amp_cert_mock):
        self.CONF.config(group="api_settings",
                         default_provider_driver='amphora')

        session.return_value = session
        cert_exp_amp_mock.return_value = None
        cr = house_keeping.CertRotation()
        cr.rotate()
        self.assertFalse(amp_cert_mock.called)

    @mock.patch('octavia.controller.worker.v2.controller_worker.'
                'ControllerWorker.amphora_cert_rotation')
    @mock.patch('octavia.db.repositories.AmphoraRepository.'
                'get_cert_expiring_amphora')
    @mock.patch('octavia.db.api.get_session')
    def test_cert_rotation_expired_amphora_with_exception_amphorav2(
            self, session, cert_exp_amp_mock, amp_cert_mock):
        self.CONF.config(group="api_settings",
                         default_provider_driver='amphorav2')

        amphora = mock.MagicMock()
        amphora.id = AMPHORA_ID

        session.return_value = session
        cert_exp_amp_mock.side_effect = [amphora, TestException(
            'break_while')]

        cr = house_keeping.CertRotation()
        self.assertRaises(TestException, cr.rotate)
        amp_cert_mock.assert_called_once_with(AMPHORA_ID)

    @mock.patch('octavia.controller.worker.v2.controller_worker.'
                'ControllerWorker.amphora_cert_rotation')
    @mock.patch('octavia.db.repositories.AmphoraRepository.'
                'get_cert_expiring_amphora')
    @mock.patch('octavia.db.api.get_session')
    def test_cert_rotation_expired_amphora_without_exception_amphorav2(
            self, session, cert_exp_amp_mock, amp_cert_mock):
        self.CONF.config(group="api_settings",
                         default_provider_driver='amphorav2')
        amphora = mock.MagicMock()
        amphora.id = AMPHORA_ID

        session.return_value = session
        cert_exp_amp_mock.side_effect = [amphora, None]

        cr = house_keeping.CertRotation()

        self.assertIsNone(cr.rotate())
        amp_cert_mock.assert_called_once_with(AMPHORA_ID)

    @mock.patch('octavia.controller.worker.v2.controller_worker.'
                'ControllerWorker.amphora_cert_rotation')
    @mock.patch('octavia.db.repositories.AmphoraRepository.'
                'get_cert_expiring_amphora')
    @mock.patch('octavia.db.api.get_session')
    def test_cert_rotation_non_expired_amphora_amphorav2(
            self, session, cert_exp_amp_mock, amp_cert_mock):
        self.CONF.config(group="api_settings",
                         default_provider_driver='amphorav2')
        session.return_value = session
        cert_exp_amp_mock.return_value = None
        cr = house_keeping.CertRotation()
        cr.rotate()
        self.assertFalse(amp_cert_mock.called)
