/** The tools that send checks to A.C.O.R.N, named for people, by the source each check arrives under. Shared by Client posture, Fleet posture and Platform health. */
export const TOOL_CHECK_LABELS: Record<string, string> = {
  threatmate: "ThreatMate",
  "threatmate-google": "Google Workspace (ThreatMate)",
  liongard: "Liongard",
  itglue: "IT Glue",
  fieldeffect: "Field Effect",
  "cipp-health": "Microsoft 365 health (CIPP)",
  ninjaone: "NinjaOne",
  halopsa: "HaloPSA",
  meraki: "Meraki",
  slide: "Slide",
  autoelevate: "AutoElevate",
  huntress: "Huntress",
  dnsfilter: "DNSFilter",
  inky: "INKY",
  "datto-saas-seats": "Datto SaaS Protection",
};
