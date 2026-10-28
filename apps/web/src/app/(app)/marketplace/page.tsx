import { redirect } from 'next/navigation';

/** The Marketplace was folded into the Playbooks page, which lists the shared library of shipped playbooks. */
export default function MarketplaceMoved(): never {
  redirect('/playbooks');
}
