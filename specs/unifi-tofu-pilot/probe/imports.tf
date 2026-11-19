terraform {
  required_providers {
    unifi = { source = "ubiquiti-community/unifi", version = "= 0.65.0" }
  }
}
provider "unifi" {
  api_url        = "https://192.168.1.1"
  allow_insecure = true
  site           = "default"
}
import {
  to = unifi_firewall_group.fw_dns_infra
  id = "3deaee48-af4b-4a49-9ea8-6ff4c086f142"
}
import {
  to = unifi_firewall_group.fw_dns_ports
  id = "e796b77d-61d8-40e1-9b65-8657e388b772"
}
import {
  to = unifi_firewall_group.fw_doh_endpoints
  id = "0eb3a16c-09a7-4f53-bed9-83e23049d9f7"
}
import {
  to = unifi_firewall_group.fw_doh_ports
  id = "2aaf6145-d92f-46c0-a915-73dfaa2810bf"
}
import {
  to = unifi_firewall_policy.p01
  id = "1c13af90-c595-485a-96a9-85aeeacdde79"
}
import {
  to = unifi_firewall_policy.p02
  id = "0e9c9360-bfab-4e94-adc5-bb079216a8c9"
}
import {
  to = unifi_firewall_policy.p03
  id = "816046cb-29c8-41e1-bfbc-d28444551822"
}
import {
  to = unifi_firewall_policy.p04
  id = "17bb9323-0a32-4252-bec3-4dd8992c6f14"
}
import {
  to = unifi_firewall_policy.p05
  id = "24d34789-0b16-41f2-be10-c61cb3fba44f"
}
import {
  to = unifi_firewall_policy.p06
  id = "04ac56cf-9d13-482e-8803-e5fce10e61f9"
}
import {
  to = unifi_firewall_policy.p07
  id = "b8e46632-a8af-410a-8949-9dd95e82e880"
}
import {
  to = unifi_firewall_policy.p08
  id = "0aa75460-f12c-4fad-926f-82c9640f908e"
}
import {
  to = unifi_firewall_policy.p09
  id = "08283c78-4c2b-4e6a-8a29-a48ff72cb8f1"
}
import {
  to = unifi_firewall_policy.p10
  id = "39cb95ea-eb59-4054-880c-1d061fbef4a9"
}
import {
  to = unifi_firewall_policy.p11
  id = "795f522c-e66d-4e22-89ea-a0ca04afba16"
}
import {
  to = unifi_firewall_policy.p12
  id = "088de448-0611-4f91-b789-a6e1b3ea909e"
}
import {
  to = unifi_firewall_policy.p13
  id = "3f9095ea-77d6-4394-98cc-3d74d0cb2534"
}
import {
  to = unifi_firewall_policy.p14
  id = "319aefb8-fc17-480a-a570-c6b55f9cc35b"
}
import {
  to = unifi_firewall_policy.p15
  id = "261588a6-5042-4c04-ae9f-3c43c5994a32"
}
import {
  to = unifi_firewall_policy.p16
  id = "c1244f3b-5c65-4120-a4b0-3af3939768fe"
}
import {
  to = unifi_firewall_policy.p17
  id = "dbbc152d-1c6b-44d7-a19c-8f905fd63991"
}
import {
  to = unifi_firewall_policy.p18
  id = "ffd67a21-deb4-47dc-a41c-d86bc118082c"
}
import {
  to = unifi_firewall_policy.p19
  id = "6776a95d-d4c3-4f96-91f8-e3bdd2fb8ac2"
}
import {
  to = unifi_firewall_policy.p20
  id = "05548df8-a937-4bf6-9bd7-3939ec2cb56f"
}
