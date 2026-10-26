# Amsterdam address snapshot

This POC searches **8,910 real addresses across 167 streets** in Amsterdam
postcode area **1012**. This is Lantern Pizza's demo delivery area.

## Source and licence

- Publisher: Netherlands Kadaster / Basisregistratie Adressen en Gebouwen (BAG).
- [OpenAddresses source metadata](https://github.com/openaddresses/openaddresses/blob/master/sources/nl/countrywide.json).
- [Source archive, dated 3 June 2026](https://data.openaddresses.io/cache/uploads/jeffdefacto/2026-06-03-bd3bf/verblijfsobject.csv.zip).
- [BAG GeoPackage information](https://www.kadaster.nl/zakelijk/producten/adressen-en-gebouwen/bag-geopackage).
- Licence: [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/), as recorded in the OpenAddresses source metadata. This data licence is separate from the repository's MIT code licence.
- Extraction date: 11 October 2026.
- CSV SHA-256: `1afa08958ed49b4c2330ece73de275264eb50a4d92b1df20db3fa857bf62e77a`.

The extractor keeps records whose city is Amsterdam, whose postcode starts with
1012, and whose object status starts with `Verblijfsobject in gebruik` (in use).
It combines house number, letter and addition, removes duplicate addresses, and
retains the BAG address identifier. Street names, numbers and postcodes are not
invented for the example. Coordinates and unrelated property fields are omitted.

## Reproduce the snapshot

Download the linked Netherlands archive (about 401 MiB compressed), then run:

```bash
uv run python -m agent_observability.utilities.addresses.bootstrap /path/to/verblijfsobject.csv.zip
```

The national file is needed only to rebuild the snapshot. The shipped local CSV
is about 462 KiB and lookup makes no network requests.

The address utility owns loading, matching and rebuilding this resource. The
normal startup uses the bundled snapshot without a download or import step.

The source is a dated snapshot. A match means a record exists here; an absent
record means “not found,” not “this building cannot exist.” A production provider
would need maintained data, adequate coverage and an operational failure path.
