"""Validate disabled public preparations only. Does not create network resources."""
from pathlib import Path
import hashlib
import ipaddress
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'poc'))
from cmdbox_gateway.stock_drive import dummy_bundle,parse_manifest,verify_prepared_flow


def check():
    bundle=json.loads((ROOT/'templates/stock-drive-runtime.json').read_text())
    assert bundle==dummy_bundle() and bundle['manifest']['enabled'] is False
    test={**bundle['manifest'],'enabled':True}
    for policy in parse_manifest(test):verify_prepared_flow(bundle['flows'][policy.uid],policy)
    plan=json.loads((ROOT/'templates/stock-drive-egress-review.json').read_text())
    assert plan['enabled'] is False and plan['status']=='PROPOSAL-ONLY-NOT-APPLIED'
    assert not any(plan[x] for x in ('tlsTerminates','caChanges','httpProxyEnvChanges','autoApplyImplemented',
                                   'actualApOrGoogleTrafficTested','stoppedInternalHttpProbesIncluded'))
    assert plan['offlineNginxPreflightExecuted'] is True and plan['offlineListenSubstituted'] is True
    assert plan['exactDeploymentBindVerified'] is False and plan['nginxVersion']=='1.30.5'
    assert plan['publishedPorts']==[] and plan['apNetworkMode']=='STRICT' and plan['maxWindowSeconds']==7200
    relay,ap=plan['relayIpv4'],plan['approvedApIpv4']
    network=ipaddress.ip_network(plan['internalSubnet'])
    assert ipaddress.ip_address(relay) in network and ipaddress.ip_address(ap) in network and relay!=ap
    assert plan['apSsrfAllowListAdd']==[relay]
    hosts={'oauth2.googleapis.com','www.googleapis.com'}
    assert plan['apHostnameMapping']=={h:relay for h in hosts}
    assert set(plan['sniUpstreams'])=={h+':443' for h in hosts}
    conf=(ROOT/'templates/stock-drive-relay.nginx.conf').read_bytes()
    assert hashlib.sha256(conf).hexdigest()==plan['configSha256']
    text=conf.decode()
    assert 'default "";' in text and 'ssl_preread on;' in text and 'deny all;' in text
    assert 'listen '+relay+':443;' in text and 'allow '+ap+';' in text
    assert 'ssl_certificate' not in text and 'ssl_certificate_key' not in text
    print('PASS disabled stock template/receipt and review-only relay scope/digest; no runtime/network test')

if __name__=='__main__':check()
