import { redirect } from "next/navigation";

/** The guide lives under Settings now (/settings/guide); this keeps old links and bookmarks working. */
export default function GuidePage(): never {
  redirect("/settings/guide");
}
