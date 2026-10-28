import { redirect } from 'next/navigation';

/** The Detection Catalog was folded into the Rules page: the imported Sigma rules are Rule packs there. */
export default function DetectionCatalogMoved(): never {
  redirect('/detection');
}
