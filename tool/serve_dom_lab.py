#!/usr/bin/env python3
"""Optional Gradio host for an audited local HTML fragment; no remote acquisition."""
import argparse
from html import escape
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_ui import render_document


def build_demo(fragment, *, css=''):
    import gradio as gr
    document = render_document(trusted_html=fragment, css=css, title='Local DOM lab')
    # Isolate site CSS from Gradio. Scripts and remote origins are not enabled.
    iframe = '<iframe id="dom-lab" title="Local DOM fixture" sandbox="" srcdoc="' + escape(document, quote=True) + '" style="width:100%;height:28rem"></iframe>'
    with gr.Blocks(analytics_enabled=False) as demo:
        gr.HTML(iframe)
    return demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html', type=Path, help='audited local HTML fragment')
    parser.add_argument('--css', type=Path)
    parser.add_argument('--port', type=int, default=7860)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024..65535')
    demo = build_demo(args.html.read_text(encoding='utf-8'),
                      css=args.css.read_text(encoding='utf-8') if args.css else '')
    demo.launch(server_name='127.0.0.1', server_port=args.port, share=False, inbrowser=False)


if __name__ == '__main__':
    main()
