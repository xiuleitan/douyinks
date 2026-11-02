from douyinks.network import is_private_ipv4, unique_lan_ips


def test_is_private_ipv4_accepts_lan_addresses_only():
    assert is_private_ipv4("192.168.1.23") is True
    assert is_private_ipv4("10.0.0.5") is True
    assert is_private_ipv4("127.0.0.1") is False
    assert is_private_ipv4("169.254.1.2") is False
    assert is_private_ipv4("8.8.8.8") is False
    assert is_private_ipv4("not-an-ip") is False


def test_unique_lan_ips_filters_and_preserves_order():
    assert unique_lan_ips(["127.0.0.1", "192.168.1.23", "192.168.1.23", "10.0.0.5"]) == [
        "192.168.1.23",
        "10.0.0.5",
    ]
