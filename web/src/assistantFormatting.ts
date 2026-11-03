/** Improve older comparison prose without changing its evidence or generic chat. */
export function formatAssistantText(text: string): string {
  // Fenced examples and code are source material, not interface copy.
  return text.split(/(```[^]*?```|~~~[^]*?~~~)/g).map((part, index) => {
    if (index % 2) return part;
    const routes = part.match(/(?:^|\n)\s*\d+[.)]\s+(?:Build|Buy)\b/gi);
    if (!routes || routes.length < 2) return part;
    return part
      .replace(/(^|\n)\s*\d+[.)]\s+((?:Build|Buy)\b[^\n]*)/gi, (_match, start: string, line: string) => {
        // Older responses put title, evidence and caveats on a single line.
        const boundary = line.search(/\s+(?:[-—–]\s+)?(?:source|cost|scope|tradeoffs?):|\s+[—–]\s+|(?<=[.!?])\s+/i);
        if (boundary < 0) return `${start}\n### ${line}\n`;
        return `${start}\n### ${line.slice(0, boundary)}\n\n${line.slice(boundary).trim()}\n`;
      })
      .replace(/(^|\n)(?:[-—–]\s*)?source:\s*/gi, '$1**Source:** ')
      .replace(/\s+[-—–]\s+(?=(?:reviewed reference|reference reviewed|page retrieved)\b)/gi, '\n\n**Cost basis:** ')
      .replace(/\s+(Cost|Scope|Tradeoffs?):\s*/gi, '\n\n**$1:** ');
  }).join('');
}

/** Bare source URLs receive a meaningful visible label; destinations stay exact. */
export function sourceLinkLabel(href: string): string {
  try {
    const url = new URL(href);
    const host = url.hostname.replace(/^www\./, '');
    if (host === 'github.com') {
      const [, owner, repository] = url.pathname.split('/');
      return owner && repository ? `${owner}/${repository} project reference` : 'GitHub reference';
    }
    if (host === 'jubilee3d.com') return 'Jubilee project reference';
    if (host === 'opentrons.com' || host.endsWith('.opentrons.com')) return 'Opentrons reference';
    return `${host} reference`;
  } catch { return href; }
}
