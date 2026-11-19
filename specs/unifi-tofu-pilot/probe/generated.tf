# __generated__ by OpenTofu
# Please review these resources and move them into your main configuration files.

# __generated__ by OpenTofu from "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
resource "unifi_firewall_group" "fw_doh_endpoints" {
  members  = ["1.0.0.1", "1.1.1.1", "149.112.112.112", "185.228.168.9", "185.228.169.9", "194.242.2.2", "208.67.220.220", "208.67.222.222", "45.90.28.0", "45.90.30.0", "76.76.10.0", "76.76.2.0", "8.8.4.4", "8.8.8.8", "9.9.9.9", "94.140.14.14", "94.140.15.15"]
  name     = "fw-doh-endpoints"
  site     = "default"
  timeouts = null
  type     = "address-group"
}

# __generated__ by OpenTofu from "1c13af90-c595-485a-96a9-85aeeacdde79"
resource "unifi_firewall_policy" "p01" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra resolvers out (Unbound+bootstrap)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "795f522c-e66d-4e22-89ea-a0ca04afba16"
resource "unifi_firewall_policy" "p11" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "c1168cec-1bb1-4efd-9d59-fcc92f4d5580"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra to DoH endpoints (invariant exemption)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "08283c78-4c2b-4e6a-8a29-a48ff72cb8f1"
resource "unifi_firewall_policy" "p09" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra to DoH endpoints (invariant exemption)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "0e9c9360-bfab-4e94-adc5-bb079216a8c9"
resource "unifi_firewall_policy" "p02" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "a9882c6d-19cf-497f-8b96-cc7f4f45a145"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra resolvers out (Unbound+bootstrap)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "b8e46632-a8af-410a-8949-9dd95e82e880"
resource "unifi_firewall_policy" "p07" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "c1168cec-1bb1-4efd-9d59-fcc92f4d5580"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "39cb95ea-eb59-4054-880c-1d061fbef4a9"
resource "unifi_firewall_policy" "p10" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "a9882c6d-19cf-497f-8b96-cc7f4f45a145"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra to DoH endpoints (invariant exemption)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "e796b77d-61d8-40e1-9b65-8657e388b772"
resource "unifi_firewall_group" "fw_dns_ports" {
  members  = ["53", "853"]
  name     = "fw-dns-ports"
  site     = "default"
  timeouts = null
  type     = "port-group"
}

# __generated__ by OpenTofu from "6776a95d-d4c3-4f96-91f8-e3bdd2fb8ac2"
resource "unifi_firewall_policy" "p19" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "c1168cec-1bb1-4efd-9d59-fcc92f4d5580"
  }
  enabled                 = true
  ip_version              = "IPV6"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass IPv6 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "088de448-0611-4f91-b789-a6e1b3ea909e"
resource "unifi_firewall_policy" "p12" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "6bfba301-6a88-4b37-bfdb-10f19cafc454"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra to DoH endpoints (invariant exemption)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "261588a6-5042-4c04-ae9f-3c43c5994a32"
resource "unifi_firewall_policy" "p15" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "c1168cec-1bb1-4efd-9d59-fcc92f4d5580"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block DoH endpoints on :443 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "816046cb-29c8-41e1-bfbc-d28444551822"
resource "unifi_firewall_policy" "p03" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "c1168cec-1bb1-4efd-9d59-fcc92f4d5580"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra resolvers out (Unbound+bootstrap)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
resource "unifi_firewall_group" "fw_doh_ports" {
  members  = ["443"]
  name     = "fw-doh-ports"
  site     = "default"
  timeouts = null
  type     = "port-group"
}

# __generated__ by OpenTofu from "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
resource "unifi_firewall_group" "fw_dns_infra" {
  members  = ["192.168.1.48/28", "192.168.1.70"]
  name     = "fw-dns-infra"
  site     = "default"
  timeouts = null
  type     = "address-group"
}

# __generated__ by OpenTofu from "319aefb8-fc17-480a-a570-c6b55f9cc35b"
resource "unifi_firewall_policy" "p14" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "a9882c6d-19cf-497f-8b96-cc7f4f45a145"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block DoH endpoints on :443 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "0aa75460-f12c-4fad-926f-82c9640f908e"
resource "unifi_firewall_policy" "p08" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "6bfba301-6a88-4b37-bfdb-10f19cafc454"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "c1244f3b-5c65-4120-a4b0-3af3939768fe"
resource "unifi_firewall_policy" "p16" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "6bfba301-6a88-4b37-bfdb-10f19cafc454"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block DoH endpoints on :443 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "05548df8-a937-4bf6-9bd7-3939ec2cb56f"
resource "unifi_firewall_policy" "p20" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "6bfba301-6a88-4b37-bfdb-10f19cafc454"
  }
  enabled                 = true
  ip_version              = "IPV6"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass IPv6 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "3f9095ea-77d6-4394-98cc-3d74d0cb2534"
resource "unifi_firewall_policy" "p13" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block DoH endpoints on :443 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "04ac56cf-9d13-482e-8803-e5fce10e61f9"
resource "unifi_firewall_policy" "p06" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "a9882c6d-19cf-497f-8b96-cc7f4f45a145"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "ffd67a21-deb4-47dc-a41c-d86bc118082c"
resource "unifi_firewall_policy" "p18" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "a9882c6d-19cf-497f-8b96-cc7f4f45a145"
  }
  enabled                 = true
  ip_version              = "IPV6"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass IPv6 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "dbbc152d-1c6b-44d7-a19c-8f905fd63991"
resource "unifi_firewall_policy" "p17" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  enabled                 = true
  ip_version              = "IPV6"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass IPv6 (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "17bb9323-0a32-4252-bec3-4dd8992c6f14"
resource "unifi_firewall_policy" "p04" {
  action                = "ALLOW"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "6bfba301-6a88-4b37-bfdb-10f19cafc454"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = false
  match_opposite_protocol = false
  name                    = "Allow DNS-infra resolvers out (Unbound+bootstrap)"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
    ips                     = []
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "IP"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}

# __generated__ by OpenTofu from "24d34789-0b16-41f2-be10-c61cb3fba44f"
resource "unifi_firewall_policy" "p05" {
  action                = "BLOCK"
  connection_state_type = "ALL"
  connection_states     = []
  create_allow_respond  = false
  description           = ""
  destination = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = "e796b77d-61d8-40e1-9b65-8657e388b772"
    port_matching_type      = "OBJECT"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  enabled                 = true
  ip_version              = "IPV4"
  logging                 = true
  match_opposite_protocol = false
  name                    = "Block public DNS bypass (force Pi-hole) [LOG]"
  protocol                = "tcp_udp"
  schedule = {
    date           = null
    date_end       = null
    date_start     = null
    mode           = "ALWAYS"
    normalize      = false
    repeat_on_days = []
    time = {
      all_day = false
      range = {
        end   = null
        start = null
      }
    }
  }
  site = "default"
  source = {
    client_macs             = null
    iid                     = ""
    ip_group_id             = ""
    ips                     = null
    mac                     = ""
    match_mac               = false
    match_opposite_iid      = false
    match_opposite_ips      = false
    match_opposite_networks = false
    match_opposite_ports    = false
    matching_target         = "ANY"
    network_ids             = null
    port                    = null
    port_group_id           = ""
    port_matching_type      = "ANY"
    regions                 = null
    web_domains             = null
    zone_id                 = "bc4a5c4d-931b-4c13-ab9f-516780098681"
  }
  timeouts = null
}
