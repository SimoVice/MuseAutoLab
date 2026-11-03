import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

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
          ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
          : <span>{children}</span>,
      }}>{text}</Markdown>
  </div>;
}
