import os
import io
import json
from contextlib import contextmanager

# Force local-only mode for OpenAI operations during test
os.environ['OPENAI_API_KEY'] = ''

from app import app as flask_app  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402

@contextmanager
def test_client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c

def make_test_pdf_bytes():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, 'Test PDF for history reuse feature')
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def main():
    with test_client() as client:
        # 1) History should be empty initially
        r = client.get('/api/files/history')
        assert r.status_code == 200, r.data
        data = r.get_json() or {}
        assert 'files' in data
        print('Initial history count:', len(data['files']))

        # 2) Upload a PDF
        pdf_buf = make_test_pdf_bytes()
        data = {
            'verbosity': 'detailed'
        }
        # Werkzeug test client needs file tuple: (file_object, filename)
        r = client.post('/upload', data={**data, 'pdf': (pdf_buf, 'history_test.pdf')}, content_type='multipart/form-data')
        assert r.status_code == 200, r.data
        up = r.get_json() or {}
        print('Upload response keys:', sorted(list(up.keys())))
        assert 'history_id' in up, up
        hid = up['history_id']

        # 3) History should now have at least one file
        r = client.get('/api/files/history')
        assert r.status_code == 200, r.data
        hist = r.get_json() or {}
        files = hist.get('files', [])
        print('Post-upload history count:', len(files))
        assert any(f.get('id') == hid for f in files), 'Uploaded file not found in history list'

        # 4) Use the file from history
        r = client.post('/api/files/use', json={'id': hid})
        assert r.status_code == 200, r.data
        used = r.get_json() or {}
        print('Use history response keys:', sorted(list(used.keys())))
        assert used.get('file_name', '').endswith('history_test.pdf')

        # 5) OCR meta should work now
        r = client.get('/api/ocr')
        assert r.status_code == 200, r.data
        ocr_meta = r.get_json() or {}
        print('OCR meta:', ocr_meta)
        assert (ocr_meta.get('totalPages') or 0) >= 1

    print('All history reuse tests passed.')


if __name__ == '__main__':
    main()
