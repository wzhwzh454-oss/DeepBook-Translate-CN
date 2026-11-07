"""Update Word fields and export a PDF for the host Agent's visual review.

Run with a host Python that provides pywin32. The skill's normal interpreter
does not need this optional package; the Agent can use its bundled runtime.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import tempfile

def finalize(docx, pdf):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = document = None
    try:
        app = win32com.client.DispatchEx('Word.Application')
        app.Visible = False
        app.DisplayAlerts = 0
        app.AutomationSecurity = 3
        with tempfile.TemporaryDirectory(prefix='bt-layout-', dir=str(docx.parent)) as temp:
            working = Path(temp) / docx.name
            shutil.copy2(docx, working)
            document = app.Documents.Open(str(working), ReadOnly=False, AddToRecentFiles=False)
            document.Fields.Update()
            document.Repaginate()
            for index in range(1, document.TablesOfContents.Count + 1):
                document.TablesOfContents.Item(index).Update()
            document.Repaginate()
            document.Fields.Update()
            pages = document.ComputeStatistics(2)
            document.Save()
            pdf.parent.mkdir(parents=True, exist_ok=True)
            document.ExportAsFixedFormat(str(pdf), 17)
            document.Close(False)
            document = None
            shutil.copy2(working, docx)
        return {'ok': True, 'docx': str(docx), 'pdf': str(pdf), 'pages': pages,
                'docx_sha256': hashlib.sha256(docx.read_bytes()).hexdigest(),
                'visual_review_required': True}
    finally:
        if document is not None:
            document.Close(False)
        if app is not None:
            app.Quit()
        pythoncom.CoUninitialize()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--docx', required=True, type=Path)
    parser.add_argument('--pdf', required=True, type=Path)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = finalize(args.docx.resolve(), args.pdf.resolve())
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error), 'next': 'Agent should use a host Python with pywin32 and available Word, or another available layout engine.'}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
