# Card Flip Desk

Django-app die het verkooptraject van sportkaarten bijhoudt, van inkoop tot
verkoop op eBay, en uitrekent wat er na alle kosten echt overblijft.

## Status

| MVP-stap | Onderdeel | Status |
|---|---|---|
| 1 | Project, accounts, kaartmodel, voorraad-CRUD | ✅ |
| 2 | CSV-import met kolomkoppeling en foutrapport | ✅ |
| 3 | Kostencalculator met FeeProfile (vooruit en omgekeerd) | ✅ |
| 4 | Verkopen registreren, winst per kaart en per maand | ✅ |
| 5–11 | Foto's, dashboard, listing-generator, waarschuwingen, eBay, API, docs | open |

## Starten

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo   # lokaal demo-account, zie inventory/management/commands/seed_demo.py
.venv\Scripts\python manage.py runserver
```

Tests: `.venv\Scripts\python -m pytest`

## Architectuur

```
config/      settings, urls, registratie (maakt een startkostenprofiel aan)
inventory/   Card, Purchase, CardQuerySet (filters, voorraadwaarde), CSV-import
finance/     calculator.py (pure functies), FeeProfile
sales/       Listing, Sale, SaleQuerySet (winst via subquery), services.register_sale
tests/       pytest-django
```

**Bedrijfsregels in services, niet in views.** `finance/calculator.py` heeft
geen database-afhankelijkheid; views roepen het alleen aan.

### Rekenregels (calculator)

- Alles in `Decimal`; een float geeft een `TypeError`.
- Commissie en betaalkosten over prijs + verzendopbrengst.
- Elke kostenpost apart afgerond op centen, `ROUND_HALF_UP`.
- Marge = winst / bruto × 100, op 0,1 afgerond; `None` bij bruto 0.
- Omgekeerd rekenen geeft de **laagste** prijs die de doelwinst haalt. Door
  afronding kan dat een cent onder de "naïeve" prijs liggen.

### Tarieven

Tarieven staan in `FeeProfile` (per categorie, met `valid_from`), niet in de
code. Een verkoop gebruikt het profiel dat op de verkoopdatum gold en slaat
de berekende bedragen op, zodat een latere tariefwijziging oude winsten niet
verandert. Het startprofiel (13,25 % + € 0,35) is een voorbeeld; controleer
de actuele tarieven in je eBay-account.

### Toegang

Elke view filtert op `owner=request.user` en geeft 404 (niet 403) bij
andermans data. Dit wordt per endpoint getest.
