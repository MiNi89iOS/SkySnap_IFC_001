1) Instrukcja konfiguracji srodowiska:

Korzystałem z Visual Studio Code

Wymagania:
- Python 3.14 (lub zgodny 3.x z obsluga ifcopenshell 0.8.4.post1)
- system powlokowy (np. zsh/bash)

Zastosowane biblioteki (requirements.txt):
- ifcopenshell==0.8.4.post1
  Glowna biblioteka do odczytu IFC, walidacji schematu i analizy Property Setow.
- pytest==9.0.2
  Wymagane przez walidacje IFC z opcja --express-rules (wewnetrzne reguly EXPRESS).
- numpy==2.4.2, shapely==2.1.2
  Zaleznosci obliczeniowo-geometryczne wykorzystywane przez ekosystem ifcopenshell.
- isodate==0.7.2, python-dateutil==2.9.0.post0, six==1.17.0, typing_extensions==4.15.0
  Biblioteki pomocnicze do obslugi dat, kompatybilnosci i typowania.
- iniconfig==2.3.0, packaging==26.0, pluggy==1.6.0, Pygments==2.19.2, lark==1.3.1
  Dodatkowe zaleznosci srodowiska i parserow (m.in. dla pytest/ifcopenshell).


Kroki konfiguracji:
1. W Visual Studio Code przejdz do katalogu projektu
2. Utworz srodowisko virtualne:
   python3 -m venv .venv
3. Aktywuj srodowisko:
   source .venv/bin/activate
4. Zaktualizuj pip:
   python -m pip install --upgrade pip
5. Zainstaluj zaleznosci:
   pip install -r requirements.txt

Uruchamianie narzedzi:
- Walidacja IFC:
  .venv/bin/python IFC_interpreter.py
- Pelna walidacja z regualmi EXPRESS:
  .venv/bin/python IFC_interpreter.py --express-rules
- Raport Property Setow:
  .venv/bin/python IFC_property_sets_report.py

Pliki wynikowe:
- *_VERIFICATION.txt (wynik poprawnosci)
- *_PROPERTYSETS.txt (opis Property Setow)

2) Komentarz do wyniku weryfikacji poprawnosci plikow IFC

- ANTENA_VERIFICATION.txt:
  plik ANTENA.ifc przechodzi walidacje bez bledow (0 error, 0 warning).
- SEGMENT_VERIFICATION.txt:
  plik SEGMENT.ifc ma 1 blad schematu IFC:
  IfcRelAssociatesMaterial.RelatedObjects jest atrybutem wymaganym, a w instancji #22526 nie ma poprawnej wartosci.

Interpretacja:
- ANTENA.ifc jest spojny na poziomie sprawdzanych regul.
- SEGMENT.ifc zawiera niekompletna relacje materialowa (powiazanie materialu z elementami jest niepelne), wiec plik nie jest w pelni poprawny.

3) Komentarze znaczenia Psetow obecnych w plikach IFC

- W ANTENA.ifc jedynym niestandardowym Psetem jest Pset_SkySnap.
- W SEGMENT.ifc poza Pset_SkySnap wystepuja tez inne niestandardowe (narzedziowe/projektowe) zestawy:
  Constraints, Constraints(Type), Construction, Dimensions, Geometric Position, Graphics(Type), Identity Data,
  Identity Data(Type), Materials and Finishes, Other, Other(Type), Phasing, ProfileProperties, Structural,
  Structural Analysis, Structural Section Geometry, Text.
- Standardowe IFC sa przede wszystkim Psety z katalogu buildingSMART (np. Pset_BuildingCommon, Pset_ColumnCommon,
  Pset_MemberCommon, Pset_PlateCommon, Pset_SiteCommon itd.).


1. Constraints
   Ograniczenia i zaleznosci polozenia elementu wzgledem poziomow/hosta.
2. Constraints(Type)
   Ograniczenia przypisane do typu elementu.
3. Construction
   Parametry konstrukcyjne wykonania (np. wydluzenia/przyciecia).
4. Dimensions
   Wymiary i parametry geometryczne przekroju/elementu.
5. Geometric Position
   Ustawienia pozycjonowania i justowania geometrycznego.
6. Graphics(Type)
   Ustawienia reprezentacji graficznej typu (symbolika, linie).
7. Identity Data
   Dane identyfikacyjne obiektu (nazwa, kod, powiazania).
8. Identity Data(Type)
   Dane identyfikacyjne na poziomie typu.
9. Materials and Finishes
   Informacje materialowe i wykonczeniowe.
10. Other
    Pozostale dane projektowe/administracyjne.
11. Other(Type)
    Dodatkowe metadane na poziomie typu.
12. Phasing
    Dane fazowania (etap utworzenia elementu).
13. ProfileProperties
    Wlasciwosci profilu przekroju.
14. Pset_BuildingCommon
    Standardowy IFC Pset dla budynku (np. referencja, kondygnacje).
15. Pset_BuildingElementProxyCommon
    Standardowy IFC Pset dla elementow typu proxy.
16. Pset_BuildingStoreyCommon
    Standardowy IFC Pset dla kondygnacji.
17. Pset_ColumnCommon
    Standardowy IFC Pset dla slupow (nosnosc, referencja, nachylenie).
18. Pset_CommunicationsApplianceTypeCommon
    Standardowy IFC Pset dla typu urzadzenia telekomunikacyjnego.
19. Pset_EnvironmentalImpactIndicators
    Wskazniki oddzialywania srodowiskowego elementu.
20. Pset_ManufacturerTypeInformation
    Informacje producenta dla typu wyrobu.
21. Pset_MemberCommon
    Standardowy IFC Pset dla elementow liniowych (member).
22. Pset_PlateCommon
    Standardowy IFC Pset dla plyt.
23. Pset_ReinforcementBarPitchOfColumn
    Dane zwiazane z rozstawem zbrojenia slupa.
24. Pset_SiteCommon
    Standardowy IFC Pset dla terenu (site).
25. Pset_SkySnap
    Niestandardowy (projektowy) zestaw danych domenowych SkySnap.
26. Structural
    Parametry konstrukcyjne i technologiczne lacznikow/elementow nosnych.
27. Structural Analysis
    Parametry obliczeniowe do analizy konstrukcyjnej.
28. Structural Section Geometry
    Geometria przekroju dla analiz konstrukcyjnych.
29. Text
    Pola opisowe i etykiety tekstowe.


4) Wstawiono Antenę na Segment.
