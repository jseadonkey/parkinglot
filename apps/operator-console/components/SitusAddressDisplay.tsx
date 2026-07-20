/** Render situs; approximate (nearby-street only) values are italic with a trailing *. */

type Props = {
  address: string;
  approximate?: boolean | null;
};

export function SitusAddressDisplay({ address, approximate }: Props) {
  if (!approximate) {
    return <span>{address}</span>;
  }
  return (
    <span
      title="Nearby street only — no street number on file (county assessor blank)"
      style={{ fontStyle: "italic" }}
    >
      {address}*
    </span>
  );
}
