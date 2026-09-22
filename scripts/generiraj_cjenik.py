
import csv
import io
import json
import os
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path


PREDLOZAK = Path("predlozak-proizvodi.csv")
IZLAZ = Path("probni-cjenik.csv")
API_VERZIJA = "2026-07"

SHOP = os.environ["SHOPIFY_SHOP_DOMAIN"].strip()
CLIENT_ID = os.environ["SHOPIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SHOPIFY_CLIENT_SECRET"]


def posalji_json(url, podaci, headers=None):
    tijelo = json.dumps(podaci).encode("utf-8")

    zahtjev = urllib.request.Request(
        url,
        data=tijelo,
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(zahtjev, timeout=30) as odgovor:
            return json.load(odgovor)
    except urllib.error.HTTPError as greska:
        detalji = greska.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Zahtjev nije uspio (HTTP {greska.code}): {detalji}"
        ) from greska


def dohvati_token():
    rezultat = posalji_json(
        f"https://{SHOP}/admin/oauth/access_token",
        {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )

    token = rezultat.get("access_token")

    if not token:
        raise RuntimeError("Shopify nije vratio pristupni token.")

    return token


def dohvati_proizvode(token):
    upit = """
    query($cursor: String) {
      products(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          title
          status
          metafield(
            namespace: "custom"
            key: "sidrena_cijena_10_9_2026"
          ) {
            value
          }
          variants(first: 100) {
            nodes {
              sku
              price
            }
          }
        }
      }
    }
    """

    proizvodi = []
    cursor = None

    while True:
        rezultat = posalji_json(
            f"https://{SHOP}/admin/api/{API_VERZIJA}/graphql.json",
            {
                "query": upit,
                "variables": {"cursor": cursor},
            },
            {"X-Shopify-Access-Token": token},
        )

        if rezultat.get("errors"):
            raise RuntimeError(
                "Shopify GraphQL pogreska: " + str(rezultat["errors"])
            )

        stranica = rezultat["data"]["products"]
        proizvodi.extend(stranica["nodes"])

        if not stranica["pageInfo"]["hasNextPage"]:
            break

        cursor = stranica["pageInfo"]["endCursor"]

    return proizvodi


def cijena_za_csv(vrijednost):
    try:
        broj = Decimal(str(vrijednost).replace(",", "."))
    except InvalidOperation as greska:
        raise RuntimeError(
            f"Neispravna cijena: {vrijednost}"
        ) from greska

    return f"{broj:.2f}".replace(".", ",")


def procitaj_sidrenu_cijenu(metafield):
    if metafield is None:
        raise RuntimeError("Proizvod nema upisanu sidrenu cijenu.")

    vrijednost = metafield["value"]

    try:
        zapis = json.loads(vrijednost)
    except (json.JSONDecodeError, TypeError):
        zapis = vrijednost

    if isinstance(zapis, dict):
        vrijednost = zapis["amount"]
    else:
        vrijednost = zapis

    return cijena_za_csv(vrijednost)


def ucitaj_predlozak():
    if not PREDLOZAK.exists():
        raise RuntimeError(
            "Nedostaje datoteka predlozak-proizvodi.csv "
            "u glavnoj mapi repozitorija."
        )

    with PREDLOZAK.open(
        "r", encoding="utf-8-sig", newline=""
    ) as datoteka:
        citac = csv.DictReader(datoteka, delimiter=";")
        stupci = citac.fieldnames
        redci = list(citac)

    if not stupci:
        raise RuntimeError("Predlozak nema zaglavlje.")

    obavezni = {
        "Šifra proizvoda",
        "Naziv proizvoda",
        "Aktualna cijena (EUR)",
        "Dodatna cijena (EUR)",
    }

    if not obavezni.issubset(set(stupci)):
        raise RuntimeError(
            "Predlozak nema ocekivane stupce: "
            + ", ".join(sorted(obavezni - set(stupci)))
        )

    return stupci, redci


def main():
    stupci, redci = ucitaj_predlozak()
    token = dohvati_token()
    proizvodi = dohvati_proizvode(token)

    po_sifri = {}

    for proizvod in proizvodi:
        if proizvod["status"] != "ACTIVE":
            continue

        sidrena = procitaj_sidrenu_cijenu(
            proizvod.get("metafield")
        )

        for varijanta in proizvod["variants"]["nodes"]:
            sifra = (varijanta.get("sku") or "").strip()

            if not sifra:
                continue

            if sifra in po_sifri:
                raise RuntimeError(
                    f"Ponovljena Shopify sifra: {sifra}"
                )

            po_sifri[sifra] = {
                "naziv": proizvod["title"],
                "cijena": cijena_za_csv(varijanta["price"]),
                "sidrena": sidrena,
            }

    obradene_sifre = set()
    broj_proizvoda = 0

    for redak in redci:
        sifra = redak["Šifra proizvoda"].strip()

        # Zlatne naljepnice su dodatna opcija u OPTIS-u,
        # a ne samostalan Shopify proizvod.
        if sifra == "42":
            redak["Napomena"] = (
                "Dodatna naplatna opcija od 4,00 EUR "
                "iskljucivo uz kupnju Majkulice; "
                "nije dostupna za samostalnu kupnju. "
                "Dodatna cijena = cijena primjenjiva 10.09.2026."
            )
            continue

        if sifra not in po_sifri:
            raise RuntimeError(
                f"Proizvod iz predloska nije pronaden "
                f"medu aktivnim Shopify proizvodima: {sifra}"
            )

        if sifra in obradene_sifre:
            raise RuntimeError(
                f"Ponovljena sifra u predlosku: {sifra}"
            )

        podaci = po_sifri[sifra]

        redak["Naziv proizvoda"] = podaci["naziv"]
        redak["Aktualna cijena (EUR)"] = podaci["cijena"]
        redak["Dodatna cijena (EUR)"] = podaci["sidrena"]

        if "Cijena za jedinicu mjere (EUR)" in redak:
            redak["Cijena za jedinicu mjere (EUR)"] = (
                podaci["cijena"]
            )

        obradene_sifre.add(sifra)
        broj_proizvoda += 1

    visak = set(po_sifri) - obradene_sifre

    if visak:
        raise RuntimeError(
            "Aktivni Shopify proizvodi nisu u predlosku "
            "(ili su dodane nove varijante): "
            + ", ".join(sorted(visak))
        )

    with IZLAZ.open(
        "w", encoding="utf-8-sig", newline=""
    ) as datoteka:
        pisac = csv.DictWriter(
            datoteka,
            fieldnames=stupci,
            delimiter=";",
        )
        pisac.writeheader()
        pisac.writerows(redci)

    print("PROBNI CJENIK USPJESNO IZRADEN")
    print("Shopify proizvodi:", broj_proizvoda)
    print("Ukupno stavki u CSV-u:", len(redci))
    print("Naziv probne datoteke:", IZLAZ)


if __name__ == "__main__":
    main()
