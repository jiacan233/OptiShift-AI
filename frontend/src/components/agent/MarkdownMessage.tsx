import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="break-words text-xs leading-relaxed text-slate-700 [&_a]:break-words [&_a]:text-blue-700 [&_a]:underline [&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-blue-300 [&_blockquote]:pl-3 [&_blockquote]:text-slate-500 [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.9em] [&_code]:text-blue-700 [&_h1]:my-2 [&_h1]:text-base [&_h1]:font-extrabold [&_h1]:text-slate-900 [&_h2]:my-2 [&_h2]:text-[15px] [&_h2]:font-extrabold [&_h2]:text-slate-900 [&_h3]:my-2 [&_h3]:text-sm [&_h3]:font-bold [&_h3]:text-slate-900 [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_pre]:my-2 [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-slate-900 [&_pre]:p-3 [&_pre]:text-xs [&_pre]:text-slate-100 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-slate-100 [&_table]:min-w-full [&_table]:text-xs [&_tbody_tr]:border-t [&_tbody_tr]:border-slate-200 [&_td]:px-2 [&_td]:py-1 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_thead]:bg-slate-50 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5"
    data-testid="markdown-message"
  >
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={{
        a: ({ children, href }) => (
          <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
        ),
        table: ({ children }) => (
          <div className="my-2 max-w-full overflow-x-auto">
            <table>{children}</table>
          </div>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  </div>
  )
}
