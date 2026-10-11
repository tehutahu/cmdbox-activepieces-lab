"""Actual ADK Runner, local scripted model and in-process dummy transport only."""
import asyncio
from dataclasses import replace
import json
import os
import socket
from cmdbox_gateway.core import GatewayError, invocation_scope
from cmdbox_gateway.fixtures import fixture, login, payload, context

async def exercise():
    # asyncio's Windows self-pipe is already created. Block EVERY subsequent connect,
    # including localhost; this exercise must not talk to AP or any provider.
    original, original_ex = socket.socket.connect, socket.socket.connect_ex
    blocked = []
    def deny(self, address):
        blocked.append('socket-connect')
        raise RuntimeError('Offline adapter test forbids socket connections')
    socket.socket.connect = socket.socket.connect_ex = deny
    os.environ['OTEL_SDK_DISABLED'] = 'true'
    os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'
    for name in ('GOOGLE_API_KEY', 'GEMINI_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ.pop(name, None)
    outcomes = []
    try:
        from google.adk.agents import LlmAgent
        from google.adk.models.base_llm import BaseLlm
        from google.adk.models.llm_response import LlmResponse
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types
        from cmdbox_gateway.adk_adapter import ScopedSyntheticToolset
        f = fixture(); captured = {}; declarations = []
        class RecordingToolset(ScopedSyntheticToolset):
            async def get_tools(self, readonly_context=None):
                result = await super().get_tools(readonly_context)
                captured[readonly_context.user_id] = readonly_context
                return result
        class LocalLlm(BaseLlm):
            async def generate_content_async(self, llm_request, stream=False):
                responses = [p.function_response for p in llm_request.contents[-1].parts or [] if p.function_response]
                if responses:
                    content = types.Content(role='model', parts=[types.Part(text=json.dumps(responses[-1].response))])
                else:
                    names = list(llm_request.tools_dict); declarations.append(names)
                    assert names == ['lab_identity']
                    content = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name='lab_identity', args={}))])
                usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=0, candidates_token_count=0, total_token_count=0)
                yield LlmResponse(content=content, usage_metadata=usage)
        sessions = InMemorySessionService()
        for uid in ('101', '202', '303'):
            await sessions.create_session(app_name='adapter_lab', user_id='cmdbox_uid_' + uid, session_id='same-chat')
        toolset = RecordingToolset(f.broker)
        runner = Runner(app_name='adapter_lab', session_service=sessions,
                        agent=LlmAgent(name='adapter_agent', model=LocalLlm(model='local-scripted-model'), tools=[toolset]))
        def actor(uid=101):
            wire = json.loads(json.dumps(f.issuer.attach(login(uid, 'display-' + str(uid)), payload())))
            return f.verifier.verify(wire)
        async def turn(uid):
            verified = actor(uid); events = []
            f.broker.require_actor_connection(verified)
            with invocation_scope(verified, 'same-chat'):
                async for event in runner.run_async(user_id=verified.adk_user_id, session_id='same-chat',
                                                    new_message=types.Content(role='user', parts=[types.Part(text='IDENTITY')])):
                    events.append(event.model_dump(mode='json', exclude_none=True))
            return json.dumps(events)
        async def check(name, operation):
            try:
                await operation()
                outcomes.append({'name': name, 'status': 'pass'})
            except Exception as error:
                outcomes.append({'name': name, 'status': 'fail', 'errorType': type(error).__name__})
                raise
        try:
            async def parallel():
                a, b = await asyncio.gather(turn(101), turn(202))
                assert 'A_ONLY' in a and 'B_ONLY' not in a
                assert 'B_ONLY' in b and 'A_ONLY' not in b
            await check('Signed Web job -> shared actual ADK Runner: concurrent A/B same session ID', parallel)
            async def history():
                await parallel()
                for uid, own, other in (('101', 'A_ONLY', 'B_ONLY'), ('202', 'B_ONLY', 'A_ONLY')):
                    saved = await sessions.get_session(app_name='adapter_lab', user_id='cmdbox_uid_' + uid, session_id='same-chat')
                    serialized = json.dumps([e.model_dump(mode='json') for e in saved.events])
                    assert own in serialized and other not in serialized
            await check('Repeated actual ADK turns retain separate UID histories', history)
            async def management():
                assert declarations and all(x == ['lab_identity'] for x in declarations)
                assert not toolset._use_invocation_cache
                for uid in (101, 202):
                    a = actor(uid)
                    with invocation_scope(a, 'same-chat'):
                        tools = await toolset.get_tools(captured[a.adk_user_id])
                        assert [t.name for t in tools] == ['lab_identity']
                        assert tools[0]._get_declaration().parameters.properties == {}
            await check('Only explicitly approved synthetic alias reaches actual ADK model', management)
            async def contextless():
                for ctx in (None, captured['cmdbox_uid_101']):
                    try:
                        await toolset.get_tools(ctx)
                    except GatewayError as error:
                        assert error.code == 'verified_invocation_required'
                    else:
                        raise AssertionError('Cached context must not authorize an unsigned invocation')
            await check('Cached/contextless discovery without verified invocation is refused', contextless)
            async def cached():
                a, b = actor(101), actor(202)
                with invocation_scope(a, 'same-chat'):
                    old = (await toolset.get_tools(context(a)))[0]
                before = len(f.transport.calls)
                with invocation_scope(b, 'same-chat'):
                    assert await old.run_async(args={}, tool_context=context(b)) == {'error': 'stale_or_wrong_identity_tool'}
                with invocation_scope(a, 'same-chat'):
                    assert await old.run_async(args={'uid': '202'}, tool_context=context(a)) == {'error': 'invalid_tool_arguments'}
                assert len(f.transport.calls) == before
            await check('Cached A tool cannot execute for B or accept LLM-selected UID', cached)
            async def unbound():
                before = len(f.transport.calls)
                try:
                    await turn(303)
                except GatewayError as error:
                    assert error.code == 'reconnect_required'
                else:
                    raise AssertionError('Unbound login must require reconnect')
                assert len(f.transport.calls) == before
            await check('Worker preflight: unbound UID requires reconnect before actual ADK model/transport', unbound)
            async def disabled():
                a = actor(101)
                with invocation_scope(a, 'same-chat'):
                    old = (await toolset.get_tools(context(a)))[0]
                    f.registry.disable('101')
                    assert await old.run_async(args={}, tool_context=context(a)) == {'error': 'reconnect_required'}
                b = await turn(202); assert 'B_ONLY' in b and 'A_ONLY' not in b
            await check('Revoked dummy binding refuses cached A tool; B continues', disabled)
            assert blocked == []
            return outcomes, blocked
        finally:
            await runner.close()
    finally:
        socket.socket.connect, socket.socket.connect_ex = original, original_ex
