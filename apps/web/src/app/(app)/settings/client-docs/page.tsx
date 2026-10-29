import type { Metadata } from "next";

import { ClientDocs } from "./ClientDocs";

export const metadata: Metadata = {
  title: "Client documentation | Settings | A.C.O.R.N",
};

export default function ClientDocsPage() {
  return <ClientDocs />;
}
