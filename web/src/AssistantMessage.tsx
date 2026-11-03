import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatAssistantText, sourceLinkLabel } from './assistantFormatting';
import './assistant-message.css';

/** Render assistant prose as CommonMark without HTML, embedded media or unsafe URLs. */
export default function AssistantMessage({ text }: { text: string }) {
  return <div className="assistant-markdown">
    <Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={['img']} unwrapDisallowed
      urlTransform={(value) => {
        try {
          const url = new URL(value);
          return ['https:', 'http:', 'mailto:'].includes(url.protocol) ? url.href : '';
        } catch { return ''; }
      }}
      components={{
        a: ({ href, children }) => href
          ? <a href={href} target="_blank" rel="noopener noreferrer">{String(children) === href ? sourceLinkLabel(href) : children}</a>
          : <span>{children}</span>,
        table: ({ children }) => <div className="assistant-table-scroll" tabIndex={0} role="region" aria-label="Comparison table"><table>{children}</table></div>,
      }}>{formatAssistantText(text)}</Markdown>
  </div>;
}
