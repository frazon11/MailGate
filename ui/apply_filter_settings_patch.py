from pathlib import Path

path = Path('/app/app_v2.py')
text = path.read_text(encoding='utf-8')

if 'from filter_settings import bp as filter_settings_bp' not in text:
    text = text.replace(
        'from connection_tests import test_exchange, test_provider\n',
        'from connection_tests import test_exchange, test_provider\nfrom filter_settings import bp as filter_settings_bp\n',
        1,
    )

link = '<a class="button secondary" href="/settings/filters">Spam &amp; Antivirus</a>'
if link not in text:
    marker = '<a class="button secondary" href="/logs">Logs / Status</a>'
    if marker in text:
        text = text.replace(marker, marker + ' ' + link, 1)
    else:
        text = text.replace(
            '<div class="muted">IMAP/POP3 retrieval, Rspamd and ClamAV scanning, then SMTP relay to Exchange.</div>',
            '<div class="muted">IMAP/POP3 retrieval, Rspamd and ClamAV scanning, then SMTP relay to Exchange.</div><p>' + link + '</p>',
            1,
        )

register = 'app.register_blueprint(filter_settings_bp)\n'
if register not in text:
    insert_at = text.find('\n\n@app.get("/health")')
    if insert_at == -1:
        raise RuntimeError('Could not find blueprint registration location')
    text = text[:insert_at] + '\n\n' + register + text[insert_at:]

path.write_text(text, encoding='utf-8')
