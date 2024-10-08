# Copyright 2015 Rackspace
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import os
import subprocess
from unittest import mock

from oslo_config import cfg
from oslo_config import fixture as oslo_fixture
from werkzeug import exceptions as wz_exceptions

from octavia.amphorae.backends.agent.api_server import osutils
from octavia.amphorae.backends.agent.api_server import plug
from octavia.common import constants
import octavia.tests.unit.base as base

FAKE_CIDR_IPV4 = '10.0.0.0/24'
FAKE_GATEWAY_IPV4 = '10.0.0.1'
FAKE_IP_IPV4 = '10.0.0.2'
FAKE_CIDR_IPV6 = '2001:db8::/32'
FAKE_GATEWAY_IPV6 = '2001:db8::1'
FAKE_IP_IPV6 = '2001:db8::2'
FAKE_IP_IPV6_EXPANDED = '2001:0db8:0000:0000:0000:0000:0000:0002'
FAKE_MAC_ADDRESS = 'ab:cd:ef:00:ff:22'
FAKE_INTERFACE = 'eth33'


class TestPlug(base.TestCase):
    def setUp(self):
        super().setUp()
        self.mock_platform = mock.patch("distro.id").start()
        self.mock_platform.return_value = "ubuntu"
        self.osutil = osutils.BaseOS.get_os_util()
        self.test_plug = plug.Plug(self.osutil)
        self.addCleanup(self.mock_platform.stop)

    @mock.patch('pyroute2.IPRoute', create=True)
    def test__interface_by_mac_case_insensitive_ubuntu(self, mock_ipr):
        mock_ipr_instance = mock.MagicMock()
        mock_ipr_instance.link_lookup.return_value = [33]
        mock_ipr_instance.get_links.return_value = ({
            'attrs': [('IFLA_IFNAME', FAKE_INTERFACE)]},)
        mock_ipr().__enter__.return_value = mock_ipr_instance

        interface = self.test_plug._interface_by_mac(FAKE_MAC_ADDRESS.upper())
        self.assertEqual(FAKE_INTERFACE, interface)
        mock_ipr_instance.get_links.assert_called_once_with(33)

    @mock.patch('pyroute2.IPRoute', create=True)
    def test__interface_by_mac_not_found(self, mock_ipr):
        mock_ipr_instance = mock.MagicMock()
        mock_ipr_instance.link_lookup.return_value = []
        mock_ipr().__enter__.return_value = mock_ipr_instance

        fd_mock = mock.mock_open()
        open_mock = mock.Mock()
        isfile_mock = mock.Mock()
        with mock.patch('os.open', open_mock), mock.patch.object(
                os, 'fdopen', fd_mock), mock.patch.object(
                os.path, 'isfile', isfile_mock):
            self.assertRaises(wz_exceptions.HTTPException,
                              self.test_plug._interface_by_mac,
                              FAKE_MAC_ADDRESS.upper())
        open_mock.assert_called_once_with('/sys/bus/pci/rescan', os.O_WRONLY)
        fd_mock().write.assert_called_once_with('1')

    @mock.patch('pyroute2.IPRoute', create=True)
    def test__interface_by_mac_case_insensitive_rh(self, mock_ipr):
        mock_ipr_instance = mock.MagicMock()
        mock_ipr_instance.link_lookup.return_value = [33]
        mock_ipr_instance.get_links.return_value = ({
            'attrs': [('IFLA_IFNAME', FAKE_INTERFACE)]},)
        mock_ipr().__enter__.return_value = mock_ipr_instance

        with mock.patch('distro.id', return_value='centos'):
            osutil = osutils.BaseOS.get_os_util()
            self.test_plug = plug.Plug(osutil)
            interface = self.test_plug._interface_by_mac(
                FAKE_MAC_ADDRESS.upper())
            self.assertEqual(FAKE_INTERFACE, interface)
            mock_ipr_instance.get_links.assert_called_once_with(33)

    @mock.patch('octavia.amphorae.backends.agent.api_server.plug.Plug.'
                '_interface_by_mac', return_value=FAKE_INTERFACE)
    @mock.patch('pyroute2.NSPopen', create=True)
    @mock.patch.object(plug, "webob")
    @mock.patch('pyroute2.IPRoute', create=True)
    @mock.patch('pyroute2.netns.create', create=True)
    @mock.patch('pyroute2.NetNS', create=True)
    @mock.patch('subprocess.check_output')
    @mock.patch('shutil.copytree')
    @mock.patch('os.makedirs')
    def test_plug_vip_ipv4(self, mock_makedirs, mock_copytree,
                           mock_check_output, mock_netns, mock_netns_create,
                           mock_pyroute2, mock_webob, mock_nspopen,
                           mock_by_mac):
        m = mock.mock_open()
        with mock.patch('os.open'), mock.patch.object(os, 'fdopen', m):
            self.test_plug.plug_vip(
                vip=FAKE_IP_IPV4,
                subnet_cidr=FAKE_CIDR_IPV4,
                gateway=FAKE_GATEWAY_IPV4,
                mac_address=FAKE_MAC_ADDRESS
            )
        mock_webob.Response.assert_any_call(json={
            'message': 'OK',
            'details': 'VIP {vip} plugged on interface {interface}'.format(
                vip=FAKE_IP_IPV4, interface='eth1')
        }, status=202)
        calls = [mock.call('amphora-haproxy', ['/sbin/sysctl', '--system'],
                           stdout=subprocess.PIPE),
                 mock.call('amphora-haproxy', ['modprobe', 'ip_vs'],
                           stdout=subprocess.PIPE),
                 mock.call('amphora-haproxy',
                           ['/sbin/sysctl', '-w', 'net.ipv4.ip_forward=1'],
                           stdout=subprocess.PIPE),
                 mock.call('amphora-haproxy',
                           ['/sbin/sysctl', '-w', 'net.ipv4.vs.conntrack=1'],
                           stdout=subprocess.PIPE)]
        mock_nspopen.assert_has_calls(calls, any_order=True)

    @mock.patch('octavia.amphorae.backends.agent.api_server.plug.Plug.'
                '_interface_by_mac', return_value=FAKE_INTERFACE)
    @mock.patch('pyroute2.NSPopen', create=True)
    @mock.patch.object(plug, "webob")
    @mock.patch('pyroute2.IPRoute', create=True)
    @mock.patch('pyroute2.netns.create', create=True)
    @mock.patch('pyroute2.NetNS', create=True)
    @mock.patch('subprocess.check_output')
    @mock.patch('shutil.copytree')
    @mock.patch('os.makedirs')
    def test_plug_vip_ipv6(self, mock_makedirs, mock_copytree,
                           mock_check_output, mock_netns, mock_netns_create,
                           mock_pyroute2, mock_webob, mock_nspopen,
                           mock_by_mac):
        conf = self.useFixture(oslo_fixture.Config(cfg.CONF))
        conf.config(group='controller_worker',
                    loadbalancer_topology=constants.TOPOLOGY_ACTIVE_STANDBY)
        m = mock.mock_open()
        with mock.patch('os.open'), mock.patch.object(os, 'fdopen', m):
            self.test_plug.plug_vip(
                vip=FAKE_IP_IPV6,
                subnet_cidr=FAKE_CIDR_IPV6,
                gateway=FAKE_GATEWAY_IPV6,
                mac_address=FAKE_MAC_ADDRESS
            )
        mock_webob.Response.assert_any_call(json={
            'message': 'OK',
            'details': 'VIP {vip} plugged on interface {interface}'.format(
                vip=FAKE_IP_IPV6_EXPANDED, interface='eth1')
        }, status=202)
        calls = [mock.call('amphora-haproxy', ['/sbin/sysctl', '--system'],
                           stdout=subprocess.PIPE),
                 mock.call('amphora-haproxy', ['modprobe', 'ip_vs'],
                           stdout=subprocess.PIPE),
                 mock.call('amphora-haproxy',
                           ['/sbin/sysctl', '-w',
                            'net.ipv6.conf.all.forwarding=1'],
                           stdout=subprocess.PIPE),
                 mock.call('amphora-haproxy',
                           ['/sbin/sysctl', '-w', 'net.ipv4.vs.conntrack=1'],
                           stdout=subprocess.PIPE)]
        mock_nspopen.assert_has_calls(calls, any_order=True)

    @mock.patch.object(plug, "webob")
    @mock.patch('pyroute2.IPRoute', create=True)
    @mock.patch('pyroute2.netns.create', create=True)
    @mock.patch('pyroute2.NetNS', create=True)
    @mock.patch('subprocess.check_output')
    @mock.patch('shutil.copytree')
    @mock.patch('os.makedirs')
    def test_plug_vip_bad_ip(self, mock_makedirs, mock_copytree,
                             mock_check_output, mock_netns, mock_netns_create,
                             mock_pyroute2, mock_webob):
        m = mock.mock_open()
        with mock.patch('os.open'), mock.patch.object(os, 'fdopen', m):
            self.test_plug.plug_vip(
                vip="error",
                subnet_cidr=FAKE_CIDR_IPV4,
                gateway=FAKE_GATEWAY_IPV4,
                mac_address=FAKE_MAC_ADDRESS
            )
        mock_webob.Response.assert_any_call(json={'message': 'Invalid VIP'},
                                            status=400)

    @mock.patch('pyroute2.NetNS', create=True)
    def test__netns_interface_exists(self, mock_netns):

        netns_handle = mock_netns.return_value.__enter__.return_value

        netns_handle.get_links.return_value = [{
            'attrs': [['IFLA_ADDRESS', '123']]}]

        # Interface is found in netns
        self.assertTrue(self.test_plug._netns_interface_exists('123'))

        # Interface is not found in netns
        self.assertFalse(self.test_plug._netns_interface_exists('321'))


class TestPlugNetwork(base.TestCase):
    def setUp(self):
        super().setUp()
        self.mock_platform = mock.patch("distro.id").start()

    def __generate_network_file_text_static_ip(self):
        netns_interface = 'eth1234'
        FIXED_IP = '192.0.2.2'
        BROADCAST = '192.0.2.255'
        SUBNET_CIDR = '192.0.2.0/24'
        NETMASK = '255.255.255.0'
        DEST1 = '198.51.100.0/24'
        DEST2 = '203.0.113.0/24'
        NEXTHOP = '192.0.2.1'
        MTU = 1450
        fixed_ips = [{'ip_address': FIXED_IP,
                      'subnet_cidr': SUBNET_CIDR,
                      'host_routes': [
                          {'destination': DEST1, 'nexthop': NEXTHOP},
                          {'destination': DEST2, 'nexthop': NEXTHOP}
                      ]}]
        format_text = (
            '\n\n# Generated by Octavia agent\n'
            'auto {netns_interface}\n'
            'iface {netns_interface} inet static\n'
            'address {fixed_ip}\n'
            'broadcast {broadcast}\n'
            'netmask {netmask}\n'
            'mtu {mtu}\n'
            'up route add -net {dest1} gw {nexthop} dev {netns_interface}\n'
            'down route del -net {dest1} gw {nexthop} dev {netns_interface}\n'
            'up route add -net {dest2} gw {nexthop} dev {netns_interface}\n'
            'down route del -net {dest2} gw {nexthop} dev {netns_interface}\n'
            'post-up /usr/local/bin/lvs-masquerade.sh add ipv4 eth1234\n'
            'post-down /usr/local/bin/lvs-masquerade.sh delete ipv4 eth1234\n')

        template_port = osutils.j2_env.get_template('plug_port_ethX.conf.j2')
        text = self.test_plug._osutils._generate_network_file_text(
            netns_interface, fixed_ips, MTU, template_port)
        expected_text = format_text.format(netns_interface=netns_interface,
                                           fixed_ip=FIXED_IP,
                                           broadcast=BROADCAST,
                                           netmask=NETMASK,
                                           mtu=MTU,
                                           dest1=DEST1,
                                           dest2=DEST2,
                                           nexthop=NEXTHOP)
        self.assertEqual(expected_text, text)

    def __generate_network_file_text_two_static_ips(self):
        netns_interface = 'eth1234'
        FIXED_IP = '192.0.2.2'
        BROADCAST = '192.0.2.255'
        SUBNET_CIDR = '192.0.2.0/24'
        NETMASK = '255.255.255.0'
        DEST1 = '198.51.100.0/24'
        DEST2 = '203.0.113.0/24'
        NEXTHOP = '192.0.2.1'
        MTU = 1450
        FIXED_IP_IPV6 = '2001:0db8:0000:0000:0000:0000:0000:0001'
        BROADCAST_IPV6 = '2001:0db8:ffff:ffff:ffff:ffff:ffff:ffff'
        SUBNET_CIDR_IPV6 = '2001:db8::/32'
        NETMASK_IPV6 = '32'
        fixed_ips = [{'ip_address': FIXED_IP,
                      'subnet_cidr': SUBNET_CIDR,
                      'host_routes': [
                          {'destination': DEST1, 'nexthop': NEXTHOP},
                          {'destination': DEST2, 'nexthop': NEXTHOP}
                      ]},
                     {'ip_address': FIXED_IP_IPV6,
                      'subnet_cidr': SUBNET_CIDR_IPV6,
                      'host_routes': []}
                     ]
        format_text = (
            '\n\n# Generated by Octavia agent\n'
            'auto {netns_interface}\n'
            'iface {netns_interface} inet static\n'
            'address {fixed_ip}\n'
            'broadcast {broadcast}\n'
            'netmask {netmask}\n'
            'mtu {mtu}\n'
            'up route add -net {dest1} gw {nexthop} dev {netns_interface}\n'
            'down route del -net {dest1} gw {nexthop} dev {netns_interface}\n'
            'up route add -net {dest2} gw {nexthop} dev {netns_interface}\n'
            'down route del -net {dest2} gw {nexthop} dev {netns_interface}\n'
            'post-up /usr/local/bin/lvs-masquerade.sh add ipv4 '
            '{netns_interface}\n'
            'post-down /usr/local/bin/lvs-masquerade.sh delete ipv4 '
            '{netns_interface}\n'
            '\n\n# Generated by Octavia agent\n'
            'auto {netns_interface}\n'
            'iface {netns_interface} inet6 static\n'
            'address {fixed_ip_ipv6}\n'
            'broadcast {broadcast_ipv6}\n'
            'netmask {netmask_ipv6}\n'
            'mtu {mtu}\n'
            'post-up /usr/local/bin/lvs-masquerade.sh add ipv6 '
            '{netns_interface}\n'
            'post-down /usr/local/bin/lvs-masquerade.sh delete ipv6 '
            '{netns_interface}\n')

        template_port = osutils.j2_env.get_template('plug_port_ethX.conf.j2')
        text = self.test_plug._osutils._generate_network_file_text(
            netns_interface, fixed_ips, MTU, template_port)
        expected_text = format_text.format(netns_interface=netns_interface,
                                           fixed_ip=FIXED_IP,
                                           broadcast=BROADCAST,
                                           netmask=NETMASK,
                                           mtu=MTU,
                                           dest1=DEST1,
                                           dest2=DEST2,
                                           nexthop=NEXTHOP,
                                           fixed_ip_ipv6=FIXED_IP_IPV6,
                                           broadcast_ipv6=BROADCAST_IPV6,
                                           netmask_ipv6=NETMASK_IPV6)
        self.assertEqual(expected_text, text)

    def _setup(self, os):
        self.mock_platform.return_value = os
        self.osutil = osutils.BaseOS.get_os_util()
        self.test_plug = plug.Plug(self.osutil)

    def test__generate_network_file_text_static_ip_ubuntu(self):
        self._setup("ubuntu")
        self.__generate_network_file_text_static_ip()

    def test__generate_network_file_text_static_ip_centos(self):
        self._setup("centos")
        self.__generate_network_file_text_static_ip()

    def test__generate_network_file_text_two_static_ips_ubuntu(self):
        self._setup("ubuntu")
        self.__generate_network_file_text_two_static_ips()

    def test__generate_network_file_text_two_static_ips_centos(self):
        self._setup("centos")
        self.__generate_network_file_text_two_static_ips()
