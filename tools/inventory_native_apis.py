"""AST inventory of pinned PUBLIC cmdbox route and agent-command declarations."""
import ast
import json
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT/'cmdbox'
assert subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()=='a429260512035aa358d49e7b319c2bfc56532742'
routes = []
for file in sorted((SOURCE/'cmdbox/app/features/web').glob('*.py')):
    for node in ast.walk(ast.parse(file.read_text(encoding='utf8'))):
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)): continue
        for decorator in node.decorator_list:
            if isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Attribute) and decorator.args and isinstance(decorator.args[0],ast.Constant):
                if isinstance(decorator.func.value,ast.Name) and decorator.func.value.id == 'app':
                    path = decorator.args[0].value
                    disposition = ('signed-UID-chat' if '/chat/ws/' in path else
                        'native-agent-landing' if path=='/agent' else
                        'native-admin-read-with-lab-role-guard' if path in ('/users/list','/groups/list') else
                        'native-password-login-only' if path.startswith('/dosignin/') else 'not-mounted-in-local-mock')
                    routes.append({'file':file.name,'method':decorator.func.attr,'path':path,'localMock':disposition})
commands = []
for file in sorted((SOURCE/'cmdbox/app/features/cli').glob('cmdbox_agent_*.py')):
    tree = ast.parse(file.read_text(encoding='utf8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.FunctionDef) and node.name=='get_cmd':
            returns = [n.value.value for n in ast.walk(node) if isinstance(n,ast.Return) and isinstance(n.value,ast.Constant)]
            for command in returns:
                commands.append({'file':file.name,'command':command,'localMock':
                    'signed-UID-native-worker' if command in ('chat','session_list','session_del') else 'not-dispatched-in-local-mock'})
report = {'cmdboxPin':'a429260512035aa358d49e7b319c2bfc56532742','routes':routes,'agentCommands':commands,
    'artifactNote':'No dedicated native artifact REST route in this pin. Generic filer/exec routes are not mounted; added lab endpoints use real ADK FileArtifactService with server-selected UID root.',
    'limits':'Source inventory plus dummy tests of selected native handlers and unmounted route groups; not a full standard UI audit or proof of upstream-wide ACL.'}
(ROOT/'docs/native-api-inventory.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print('Native public inventory: '+str(len(routes))+' route declarations, '+str(len(commands))+' agent commands')
