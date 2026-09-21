# -*- coding: utf-8 -*-
r"""Pins the engine-api server's error contract, because breaking it is invisible until scoring.

Two kinds of "nothing" arrive at a caller, and they must not look alike:

    a bad ARGUMENT      -> isError TRUE.  The caller mistyped; nothing about the store is wrong.
    absent DATA         -> isError FALSE. "No class named X" is a real, correct answer.

The second is the one with teeth: if absence ever started arriving as an error, **a correct answer would
score as a tool failure**, and nothing would say so until the scoring pass, long after the run.

CORRECTION, and it moved where this has to look. The first version of this file said the exposure was the
trap group - questions that expect "no such thing". The session that measures with this server checked
the routes instead of reasoning about them, and **no trap-group question routes to an engine-api tool at
all**; every one of them names a `Docs/AgentMemory` artefact. The real exposure is wherever an absence is
a legitimate *answer* through this server, which the routes say is four tools:

    engine_api_blast_radius   how the stack claims "no Blueprint users" - the decidable-absence claim
                              the whole blast-radius group rests on. The worst one to get wrong.
    engine_api_members        "which functions can a Blueprint NOT call"
    engine_api_platform       "not available on that console"
    engine_api_search         "nothing matches", the honest answer to a half-remembered name

So every tool is asserted here, not just the ones a trap question might reach.

Both directions were then fixed and hand-checked twice, once in each copy of the server. Hand-checking a
contract whose breakage is invisible is not a test, so this is the test.

It builds a throwaway store from the repository's own seed artefacts, which takes about a second, and
asserts the contract through `handle()` - the real JSON-RPC entry point, not the tool functions - because
the schema check that makes the distinction lives there.

Usage:  python tools/check_mcp_error_contract.py
"""
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EA = os.path.join(ROOT, 'plugins', 'ue-memory-stack', 'engine-api')
SEED = os.path.join(ROOT, 'seed')

problems = []


def call(server, tool, arguments):
    """One tools/call through the real handler. Returns (isError, first line of text)."""
    reply = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                           'params': {'name': tool, 'arguments': arguments}})
    result = reply['result']
    return result['isError'], result['content'][0]['text'].splitlines()[0]


def check(label, condition, detail):
    if not condition:
        problems.append('%s: %s' % (label, detail))


def main():
    # --- schema self-consistency, which needs no store ---------------------------------------------
    # A `required` name with no matching property makes every call to that tool fail, and the failure
    # would look like the caller's fault.
    # On sys.path rather than loaded by file location: the server imports its siblings (budget,
    # uncertainty) by bare name, the way it does when a client spawns it in its own directory.
    sys.path.insert(0, EA)
    import mcp_server as server                                          # noqa: E402

    for tool in server.TOOLS:
        schema = tool.get('inputSchema') or {}
        props = set((schema.get('properties') or {}).keys())
        for name in (schema.get('required') or []):
            check(tool['name'], name in props,
                  "declares %r as required but has no such property" % name)

    # --- the contract, which does -------------------------------------------------------------------
    # ignore_cleanup_errors, and an explicit close below: the server caches its SQLite connection, and
    # Windows will not delete a file another handle still holds. Without both, this gate would fail in
    # its own teardown after every check had passed - which is the least useful way for a gate to fail.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, 'contract.db')
        built = subprocess.run(
            [sys.executable, os.path.join(EA, 'build_api_db.py'), '--root', SEED,
             '--out', db, '--report', os.path.join(tmp, 'report.md')],
            capture_output=True, text=True)
        if built.returncode != 0 or not os.path.exists(db):
            print('  PROBLEM could not build a store from seed/ to test against:')
            print('    ' + (built.stderr or built.stdout).strip().splitlines()[-1])
            return 1

        # The module reads ENGINE_API_DB at import time, so it has to be reloaded once the store
        # exists. Reload rather than re-exec: the sibling imports are already resolved.
        os.environ['ENGINE_API_DB'] = db
        importlib.reload(server)

        # A wrong argument NAME is the caller's mistake, and the message has to say so by name.
        is_error, text = call(server, 'engine_api_class', {'class_name': 'ADCharacter'})
        check('wrong argument name', is_error, 'answered with isError false; a mistyped call must be an error')
        check('wrong argument name', "'name'" in text and "'class_name'" in text,
              'does not name both the missing argument and what arrived: %r' % text)
        check('wrong argument name', 'KeyError' not in text,
              'still leaks a KeyError, which reads as a corrupt store: %r' % text)

        # A missing argument likewise.
        is_error, text = call(server, 'engine_api_class', {})
        check('no arguments', is_error, 'answered with isError false')
        check('no arguments', "'name'" in text, 'does not name the missing argument: %r' % text)

        # THE ONE THAT MATTERS. Absent data is an answer, not a failure. A trap question's correct
        # answer must not arrive as a tool error.
        is_error, text = call(server, 'engine_api_class', {'name': 'ANoSuchClassAnywhere'})
        check('absent class', not is_error,
              'absent data came back as isError TRUE. A trap question expecting "no such thing" would '
              'now score as a tool failure, and nothing would say so until the scoring pass: %r' % text)

        # And a valid call still answers.
        is_error, text = call(server, 'engine_api_class', {'name': 'ADCharacter'})
        check('valid call', not is_error, 'a valid call reported an error: %r' % text)

        # THE ONE WITH THE MOST AT STAKE. `blast_radius` is how this stack claims "no Blueprint users",
        # and that claim is the reason an agent can stop looking instead of falling back to grepping
        # .uasset binaries. If an empty result ever became an error, the stack's own decidable-absence
        # claim would arrive as a tool failure - the finding turned into a fault.
        is_error, text = call(server, 'engine_api_blast_radius', {'symbol': 'ADCharacter::NoSuchMember'})
        check('no callers, blast_radius', not is_error,
              'an empty blast radius came back as isError TRUE. "Nothing calls this" is the ANSWER here, '
              'not a failure, and it is what lets a caller stop looking: %r' % text)
        check('no callers, blast_radius', 'walk' in text.lower() or 'blueprint' in text.lower(),
              'an empty blast radius says nothing about what the walk covered, so the negative cannot be '
              'weighed: %r' % text)

        # Declared availability: "not available on that console" is an answer, and a module nobody declared is a
        # different answer again. Neither is an error.
        is_error, text = call(server, 'engine_api_platform', {'module': 'NoSuchModuleAnywhere'})
        check('unknown module, platform', not is_error,
              'an unknown module came back as isError TRUE from engine_api_platform, so "no such module" '
              'would score as a tool failure: %r' % text)

        # The same contract for the remaining two. engine_api_class was covered first because it is the
        # one a mistyped argument hits most often; these two carry absences that are answers.
        is_error, text = call(server, 'engine_api_members', {'name': 'ANoSuchClassAnywhere'})
        check('absent class, members', not is_error,
              'absent data came back as isError TRUE from engine_api_members, so a trap question routed '
              'here would score as a tool failure: %r' % text)
        check('absent class, members', 'ANoSuchClassAnywhere' in text,
              'does not say which class it could not find, which is what makes the answer usable: %r' % text)

        # Search is the one place where "nothing matched" is the most likely correct answer of all, and
        # it has to come back as an answer carrying its own confidence note rather than as a failure.
        is_error, text = call(server, 'engine_api_search', {'query': 'zzzznosuchsymbolanywhere'})
        check('no match, search', not is_error,
              'an empty search came back as isError TRUE. "Nothing matches" is the correct answer to a '
              'trap question, not a fault: %r' % text)
        check('no match, search', 'zzzznosuchsymbolanywhere' in text,
              'does not echo the query it found nothing for: %r' % text)

        # A matching search still answers, so the assertions above cannot be satisfied by a tool that
        # simply always reports nothing.
        is_error, text = call(server, 'engine_api_search', {'query': 'ADCharacter'})
        check('matching search', not is_error, 'a search that should match reported an error: %r' % text)
        check('matching search', 'No match' not in text,
              'a search for a symbol the seed store holds reported no match, so the two search '
              'assertions above prove nothing: %r' % text)

        # Let go of the store before the temporary directory goes away.
        connection = getattr(server, '_con', None)
        if connection is not None:
            connection.close()
            server._con = None

    for p in problems:
        print('  PROBLEM %s' % p)
    if not problems:
        print('engine-api error contract: bad arguments are errors and name themselves; absent data is '
              'an ordinary answer. %d tools checked.' % len(server.TOOLS))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
