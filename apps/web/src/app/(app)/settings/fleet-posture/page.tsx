import type { Metadata } from "next";

import { FleetPosture } from "./FleetPosture";

export const metadata: Metadata = {
  title: "Fleet posture | Settings | A.C.O.R.N",
};

export default function FleetPosturePage() {
  return <FleetPosture />;
}
