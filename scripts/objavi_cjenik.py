
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


IZVOR = Path("probni-cjenik.csv")
AKTUALNI = Path("aktualni-cjenik.csv")
MAPA_ARHIVE = Path("arhiva")
POPIS_ARHIVE = Path("arhiva.json")

# Stalni dio naziva preuzet je iz dosadasnjeg cjenika.
PREFIKS = "WEB_CVRSNICKA37_OSIJEK_SWM_001"


def provjeri_probni_cjenik():
    if not IZVOR.is_file():
        raise RuntimeError(
            "Nedostaje probni-cjenik.csv. "
            "Prvo pokreni program generiraj_cjenik.py."
        )

    with IZVOR.open(
        "r", encoding="utf-8-sig", newline=""
    ) as datoteka:
        citac = csv.DictReader(datoteka, delimiter=";")
        stupci = citac.fieldnames or []
        redci = list(citac)

    potrebni_stupci = {
        "Šifra proizvoda",
        "Naziv proizvoda",
        "Aktualna cijena (EUR)",
        "Sidrena cijena (EUR)",
    }

    nedostaju = potrebni_stupci - set(stupci)

    if nedostaju:
        raise RuntimeError(
            "U probnom cjeniku nedostaju stupci: "
            + ", ".join(sorted(nedostaju))
        )

    if not redci:
        raise RuntimeError("Probni cjenik nema nijednu stavku.")

    sifre = [
        (redak.get("Šifra proizvoda") or "").strip()
        for redak in redci
    ]

    if any(not sifra for sifra in sifre):
        raise RuntimeError("Neke stavke nemaju sifru proizvoda.")

    if len(sifre) != len(set(sifre)):
        raise RuntimeError("Probni cjenik sadrzi ponovljene sifre.")

    if "42" not in sifre:
        raise RuntimeError(
            "U probnom cjeniku nedostaje stavka za zlatne naljepnice."
        )

    return len(redci)


def ucitaj_arhivu():
    if not POPIS_ARHIVE.exists():
        return []

    with POPIS_ARHIVE.open("r", encoding="utf-8") as datoteka:
        arhiva = json.load(datoteka)

    if not isinstance(arhiva, list):
        raise RuntimeError("arhiva.json mora sadrzavati popis.")

    return arhiva


def sljedeci_broj_pohrane():
    MAPA_ARHIVE.mkdir(parents=True, exist_ok=True)

    brojevi = []

    for datoteka in MAPA_ARHIVE.glob(f"{PREFIKS}_*.csv"):
        ostatak = datoteka.stem.removeprefix(f"{PREFIKS}_")
        dijelovi = ostatak.split("_")

        if dijelovi and dijelovi[0].isdigit():
            brojevi.append(int(dijelovi[0]))

    return max(brojevi, default=0) + 1


def main():
    broj_stavki = provjeri_probni_cjenik()
    arhiva = ucitaj_arhivu()

    broj_pohrane = sljedeci_broj_pohrane()
    sada = datetime.now(ZoneInfo("Europe/Zagreb"))

    datum = sada.strftime("%Y%m%d")
    vrijeme = sada.strftime("%H%M")

    naziv = (
        f"{PREFIKS}_{broj_pohrane:03d}_{datum}_{vrijeme}.csv"
    )

    arhivska_datoteka = MAPA_ARHIVE / naziv

    if arhivska_datoteka.exists():
        raise RuntimeError(
            f"Arhivska datoteka vec postoji: {arhivska_datoteka}"
        )

    # Prethodne arhivske datoteke ne brisemo.
    # Time ostaju sacuvane i dulje od 30 dana.
    shutil.copyfile(IZVOR, arhivska_datoteka)

    # Stalna poveznica za aktualni cjenik.
    shutil.copyfile(IZVOR, AKTUALNI)

    novi_zapis = {
        "naziv": naziv,
        "url": arhivska_datoteka.as_posix(),
    }

    arhiva.insert(0, novi_zapis)

    with POPIS_ARHIVE.open(
        "w", encoding="utf-8"
    ) as datoteka:
        json.dump(
            arhiva,
            datoteka,
            ensure_ascii=False,
            indent=2,
        )
        datoteka.write("\n")

    print("CJENIK PRIPREMLJEN ZA OBJAVU")
    print("Broj stavki:", broj_stavki)
    print("Arhivska datoteka:", arhivska_datoteka)
    print("Aktualni cjenik:", AKTUALNI)
    print("Popis arhive:", POPIS_ARHIVE)
    print(
        "Vrijeme pripreme:",
        sada.strftime("%d.%m.%Y. %H:%M:%S"),
    )


if __name__ == "__main__":
    main()
