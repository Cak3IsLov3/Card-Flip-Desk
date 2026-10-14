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
| 5 | Foto's per kaart (validatie, thumbnails, EXIF weg, privé-opslag) | ✅ |
| 6 | Dashboard met KPI's, grafieken en voorraadleeftijd | ✅ |
| 7 | Listing-generator met templates en controles | ✅ |
| 8–11 | Voorraadwaarschuwingen, eBay, API, docs | open |

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
inventory/   Card, Purchase, CardQuerySet (filters, voorraadwaarde), CSV-import,
             CardPhoto + photos.py (verwerking), storage.py (privé-opslag)
finance/     calculator.py (pure functies), FeeProfile
sales/       Listing, Sale, SaleQuerySet (winst via subquery), services.register_sale,
             dashboard.py (voegt queryset-cijfers samen, expliciete 'today'),
             listing_generator.py (titels/beschrijvingen uit patronen), ListingTemplate
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

### Foto's

- **Inhoud bepaalt het type.** Pillow leest de kop; alleen JPEG, PNG en WebP
  komen door. Extensie en Content-Type van de browser tellen niet.
- **Limieten vóór decoderen.** Bestandsgrootte (10 MB) en afmetingen
  (8000 px) worden gecontroleerd voordat de pixels in het geheugen komen.
- **Alles wordt hercodeerd.** Verkleind tot 1600 px plus een thumbnail van
  300 px. Daarbij verdwijnen EXIF (GPS, camera), XMP en PNG-tekstblokken; de
  EXIF-oriëntatie wordt eerst toegepast. Het kleurprofiel blijft.
- **Willekeurige namen.** `cards/<uuid>.<ext>`; de bestandsnaam van de
  gebruiker komt nergens in het pad.
- **Geen publieke URL.** Bestanden staan in `PRIVATE_MEDIA_ROOT` en worden
  uitgeleverd door een view die de eigenaar controleert
  (`Cache-Control: private`). `storage.url()` gooit bewust een fout.
  Overstappen op S3 = de `photos`-backend in `STORAGES` vervangen.
- **Maximaal één hoofdfoto**, afgedwongen met een database-constraint.
- **Opruimen na commit.** Bij verwijderen of vervangen (ook via het
  verwijderen van een kaart) gaan de bestanden pas weg als de transactie
  slaagt.
### Dashboard

- **Query's in querysets** (`SaleQuerySet.totals/per_set/with_days_to_sale`,
  `CardQuerySet.unsold_by_age`); `sales/dashboard.py` voegt ze samen en krijgt
  `today` mee, zodat periodegrenzen zonder klokmanipulatie te testen zijn.
  De hele pagina draait in een vast, getest maximum aantal query's.
- **Marge is gewogen:** totale winst ÷ totale omzet, niet het gemiddelde van
  losse marges (dan telt een kaart van € 1 even zwaar als een van € 50).
- **Dagen tot verkoop** tellen vanaf "te koop sinds", anders vanaf de eerste
  inkoopdatum.
- **Periodefilter** (30 / 90 dagen, 12 maanden, alles) geldt voor alle
  verkoopcijfers; voorraadcijfers gelden altijd voor vandaag. Maanden zonder
  verkoop staan als nul in de grafiek.
- **Grafieken** (Chart.js): één y-as per grafiek, kleuren uit CSS-variabelen
  met aparte, gevalideerde stappen voor licht en donker, tooltips, en een
  tabelweergave onder elke grafiek.
### Listing-generator

- **Patronen** met plaatshouders (`{jaar} {set} {speler} #{nummer} {variant} {conditie}`),
  per gebruiker op te slaan als template. Onbekende plaatshouders worden bij
  het opslaan geweigerd.
- **Lege velden laten niets achter:** geen losse `#`, `()` of dubbele spaties,
  en een regel als `Variant:` zonder waarde valt weg. Base-variant blijft leeg.
- **Titel max. 80 tekens** (eBay). Langer wordt afgekapt op een woordgrens,
  met een waarschuwing die noemt wat er wegvalt. Opslaan boven 80 kan niet.
- **Tekens:** Unicode wordt genormaliseerd (NFC), stuurtekens en regeleinden
  verdwijnen uit de titel; accenten blijven. Kaartgegevens worden niet
  opnieuw als patroon gelezen (`{set}` als spelersnaam blijft letterlijk).
  Alles is platte tekst en wordt bij het tonen ge-escaped.
- **Controles:** titellengte, lege velden en de fotochecklist uit stap 5.
- **Vraagprijs** toont direct de winst via de kostencalculator.
- **Concept / actief:** "actief" zet de kaart op te koop met een
  'te koop sinds'-datum; een latere verkoop gebruikt deze listing.