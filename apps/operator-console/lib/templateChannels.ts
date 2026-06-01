/** Admin template tabs in display order (email, text, voice, mail). */
export const TEMPLATE_TABS: { slug: string; label: string; hint: string }[] = [
  {
    slug: "email_outreach",
    label: "Email",
    hint: "Default subject line and email body for owner outreach.",
  },
  {
    slug: "sms_outreach",
    label: "Text message",
    hint: "SMS copy — keep it short; placeholders expand at send time.",
  },
  {
    slug: "phone_call_script",
    label: "Voice script",
    hint: "Script for live calls or AI voice outreach.",
  },
  {
    slug: "certified_mail_letter",
    label: "Certified mail",
    hint: "Printed letter body for Lob / certified mail sends.",
  },
];

export function channelLabel(channel: string): string {
  switch (channel) {
    case "email":
      return "Email";
    case "sms":
      return "Text (SMS)";
    case "phone":
      return "Voice";
    case "certified_mail":
      return "Certified mail";
    default:
      return channel;
  }
}
