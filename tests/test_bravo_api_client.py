#!/usr/bin/env python3
import subprocess, os, re, random, json

# TODO:
# 1. require that user is logged in to start.
# 2. temporarily set {revoked:true} in ~/.bravo/credstore and do logged-out checks
# 3. move ~/.bravo/credstore and do logged-out checks

# TODO: test `./bravo annotate`

def run(argv, head=None, expect_code=0, err_if_stderr=None):
    if err_if_stderr is None:
        err_if_stderr = (expect_code == 0)
    kwargs = {'stdout':subprocess.PIPE, 'stderr':subprocess.PIPE}
    if head:
        if isinstance(argv, list): argv = ' '.join(argv)
        argv += f'| head -n{int(head)}'
        kwargs['shell'] = True
    proc = subprocess.run(argv, **kwargs)
    if expect_code is not None: assert proc.returncode == expect_code, proc
    if err_if_stderr: assert len(proc.stderr) == 0, proc
    return proc

bravo_fpath = './bravo'
if not os.path.exists(bravo_fpath):
    bravo_fpath = os.path.join(os.path.dirname(__file__), '../static/tools/bravo')
    if not os.path.exists(bravo_fpath):
        raise Exception('cannot find tool `bravo`')
print('testing {}'.format(bravo_fpath))

python_aliases = ['python','python2','python2.7','python3','pypy','pypy3']
python_exes = []
for python_alias in python_aliases:
    lines = run(['which','-a',python_alias], expect_code=None).stdout.decode().split('\n')
    lines = [line for line in lines if line]
    python_exes.extend(os.path.realpath(line) for line in lines)
python_exes = list(set(python_exes))
print('using these python exes:')
for exe in python_exes: print('- {}'.format(exe))
print()


# CHECK IF USER IS AUTHENTICATED
proc = run([random.choice(python_exes), bravo_fpath, 'print-access-token'], expect_code=None)
assert (proc.returncode == 0) == (len(proc.stdout) > 5) == (len(proc.stderr) < 50), proc
currently_logged_in = (proc.returncode == 0)
if currently_logged_in:
    proc = run([random.choice(python_exes), bravo_fpath, 'query-meta'], expect_code=None)
    if proc.stderr.decode().strip() == 'not authorized' and proc.returncode == 1:
        currently_logged_in = False
print('testing LOGGED ' + ['OUT','IN'][int(currently_logged_in)])


if currently_logged_in:
    for exe in python_exes:
        proc = run([exe, bravo_fpath, 'print-access-token'])
        out = proc.stdout.decode()
        assert 100 < len(out) < 300
        assert re.match(r'^[-\._a-zA-Z0-9]{100,200}\n?$', out)

        out = run([exe, bravo_fpath, '-h']).stdout.decode()
        assert 200 < len(out) < 1000

        proc = run([exe, bravo_fpath, 'query-meta'])
        j = json.loads(proc.stdout)
        assert sorted(j.keys()) == 'api_version dataset'.split(), proc

        proc = run([exe, bravo_fpath]+'query-variant -c chr1 -p 7'.split())
        assert len(proc.stdout) == 0

        proc = run([exe, bravo_fpath]+'query-variant -c chr22 -p 16389447'.split())
        j = json.loads(proc.stdout)
        assert j == {"allele_num": 125568, "allele_freq": 0.0498614, "ref": "A", "allele_count": 6261, "pos": 16389447, "filter": "PASS", "site_quality": 255.0, "rsids": ["rs34747326"], "variant_id": "22-16389447-A-G", "alt": "G", "chrom": "22"}, proc

        proc = run([exe, bravo_fpath]+'query-variant -c chrX -p 10015'.split())
        lines = [line for line in proc.stdout.decode().split('\n') if line.strip()]
        assert len(lines) == 2
        for line in lines:
            json.loads(line)

        proc = run(f'{exe} {bravo_fpath} query-gene -n LARS', head=3)
        lines = proc.stdout.decode().split('\n')
        assert 3 <= len(lines) <= 4
        for line in lines:
            if not line.strip(): continue
            j = json.loads(line)
            assert sorted(j.keys()) == sorted('allele_count allele_freq allele_num alt chrom filter pos ref rsids site_quality variant_id'.split()), j

        proc = run(f'{exe} {bravo_fpath} query-gene -n ENSG00000169174 -o vcf', head=50)
        lines = proc.stdout.decode().split('\n')
        assert 50 <= len(lines) <= 51
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith('#'): continue
            assert int(line.split('\t')[0]) == 1, line
            assert len(line.split('\t')) == 8

        proc = run([exe, bravo_fpath]+'query-region -c chrX -s 4000 -e 900000'.split(), expect_code=1)
        assert len(proc.stdout) == 0
        assert proc.stderr.decode() == 'Regions larger than 250000 base-pairs are not allowed.\n'

        proc = run(f'{exe} {bravo_fpath} query-region -c chrX -s 4000 -e 90000 -o vcf', head=50)
        lines = proc.stdout.decode().split('\n')
        assert 50 <= len(lines) <= 51
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith('#'): continue
            assert line.split('\t')[0] == 'X', line
            assert len(line.split('\t')) == 8

    print()
    print('to log out, run:')
    print(f'"{random.choice(python_exes)}" "{bravo_fpath}" revoke')


else: # logged out
    for exe in python_exes:
        proc = run([exe, bravo_fpath, 'revoke'])
        assert proc.stdout.decode().strip() in ['No access tokens to revoke.', 'Access tokens have been successfully revoked.'], proc

        proc = run([exe, bravo_fpath, 'revoke'])
        assert proc.stdout.decode().strip() == 'No access tokens to revoke.', proc

        proc = run([exe, bravo_fpath, 'print-access-token'], expect_code=1)
        assert len(proc.stdout) == 0, proc
        assert (proc.stderr.decode().strip() == 'The current token has been revoked.  Please login with `bravo login`.' or re.match(r'^Please use `./bravo login` to login.  Currently .{1,100}/.bravo/credstore does not exist.$', proc.stderr.decode().strip())), proc

        for query in ['query-meta', 'query-region -c chr1 -s 0 -e 5000', 'annotate', 'query-gene -n TCF7L2', 'query-variant -c chr1 -p 50000']:

            proc = run([exe, bravo_fpath]+query.split(), expect_code=1)
            assert len(proc.stdout) == 0, proc
            assert proc.stderr.decode().strip() in ['not authorized', 'No access tokens found. Please login first.'], proc

    print()
    print('to log in, run:')
    print(f'"{random.choice(python_exes)}" "{bravo_fpath}" login')
