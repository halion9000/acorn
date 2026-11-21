import type { GraphNode } from '@/lib/api';

/** Where a clicked node of the attack graph leads, and what the button says. */
export interface NodeLink {
  href: string;
  label: string;
}

/**
 * The page behind a node (pure): a host is a device, a user is an identity, an alert is an alert, a technique is the ATT&CK coverage page. Addresses, domains, hashes and processes have no page of their own: null.
 * A client picked on the graph is carried along, so the page opens on the same client.
 */
export function nodeLink(node: GraphNode, client = ''): NodeLink | null {
  const withClient = client ? `&client=${encodeURIComponent(client)}` : '';
  switch (node.kind) {
    case 'host':
      return { href: `/devices?search=${encodeURIComponent(node.label)}${withClient}`, label: 'Go to device' };
    case 'user':
      return { href: `/identities?search=${encodeURIComponent(node.label)}${withClient}`, label: 'Go to identity' };
    case 'alert': {
      const id = typeof node.attributes?.alert_id === 'string' && node.attributes.alert_id ? node.attributes.alert_id : node.id.replace(/^alert:/, '');
      return id ? { href: `/alerts/${encodeURIComponent(id)}`, label: 'Go to alert' } : null;
    }
    case 'technique':
      return { href: '/detection/coverage', label: 'Go to MITRE coverage' };
    default:
      return null;
  }
}
