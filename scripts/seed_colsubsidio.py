"""Seed 44 Colsubsidio projects (verbatim) + 15 fabricated afiliados.

Idempotent:
  * ``proyectos_colsubsidio``: ``INSERT ... ON CONFLICT (proyecto, modelo) DO
    NOTHING``. ``modelo`` is ``NOT NULL DEFAULT ''`` so the two blank-modelo
    rows (ABETO, LA ARBOLEDA) match the ``(proyecto, modelo)`` natural key on a
    re-seed — a nullable ``modelo`` would let Postgres skip NULLs as
    non-conflicting and the table would grow to 46 on the second run.
  * ``afiliados_colsubsidio``: ``DELETE WHERE is_seed=true`` then re-INSERT, so
    manual (non-seed) rows survive a re-run while the seed set is replaced.

Run as::

    python -m scripts.seed_colsubsidio
    .venv/bin/python scripts/seed_colsubsidio.py

``PROYECTOS_RAW`` is a *verbatim transcription* of the workbook ``Proyectos``
sheet (44 data rows). Comma decimals ('56,29') are parsed to ``Numeric`` at
insert time; blank numeric cells become NULL (not 0); blank ``modelo`` becomes
``''``. Source quirks preserved verbatim: the VIBO ONCE B2 row
(tipo=municipio='VIS'), the VERSALLES E row (area_privada 60,6 > construida
56,29), and the sparse ABETO / LA ARBOLEDA rows.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import sys
from datetime import date
from decimal import Decimal

_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import delete, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.models.afiliado_model import AfiliadoColsubsidioEntity  # noqa: E402
from app.models.proyecto_model import ProyectoColsubsidioEntity  # noqa: E402

logger = logging.getLogger(__name__)

PROYECTOS_RAW = [
    {
        'proyecto': 'VERSALLES',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 30A sur No. 2-215. Ciudadela Maiporé - Soacha',
        'descripcion': 'Versalles cuenta con amplias zonas para compartir en familia, el 50% de la ciudadela se compone de zonas verdes y recreativas. Habita uno de los 560 apartamentos disponibles, distribuidos en 4 torres de 10 pisos con ascesor.',
        'modelo': 'A',
        'area_construida': '56,29',
        'area_privada': '50,54',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'VERSALLES',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 30A sur No. 2-215. Ciudadela Maiporé - Soacha',
        'descripcion': 'Versalles cuenta con amplias zonas para compartir en familia, el 50% de la ciudadela se compone de zonas verdes y recreativas. Habita uno de los 560 apartamentos disponibles, distribuidos en 4 torres de 10 pisos con ascesor.',
        'modelo': 'B',
        'area_construida': '51,41',
        'area_privada': '46,31',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'VERSALLES',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 30A sur No. 2-215. Ciudadela Maiporé - Soacha',
        'descripcion': 'Versalles cuenta con amplias zonas para compartir en familia, el 50% de la ciudadela se compone de zonas verdes y recreativas. Habita uno de los 560 apartamentos disponibles, distribuidos en 4 torres de 10 pisos con ascesor.',
        'modelo': 'C',
        'area_construida': '45,05',
        'area_privada': '40,58',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'VERSALLES',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 30A sur No. 2-215. Ciudadela Maiporé - Soacha',
        'descripcion': 'Versalles cuenta con amplias zonas para compartir en familia, el 50% de la ciudadela se compone de zonas verdes y recreativas. Habita uno de los 560 apartamentos disponibles, distribuidos en 4 torres de 10 pisos con ascesor.',
        'modelo': 'E',
        'area_construida': '56,29',
        'area_privada': '60,6',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'PAMPLONA',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Carrera 2 #30A - 89 sur. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'En Pamplona Maiporé es el lugar donde tu proyecto de vida empieza a hacerse realidad. Disfruta de apartamentos funcionales, completas zonas comunes y una ubicación estratégica en Soacha, con excelente conexión a Bogotá.',
        'modelo': 'A',
        'area_construida': '50,25',
        'area_privada': '45,75',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'PAMPLONA',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Carrera 2 #30A - 89 sur. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'En Pamplona Maiporé es el lugar donde tu proyecto de vida empieza a hacerse realidad. Disfruta de apartamentos funcionales, completas zonas comunes y una ubicación estratégica en Soacha, con excelente conexión a Bogotá.',
        'modelo': 'B',
        'area_construida': '58,47',
        'area_privada': '53,3',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'PAMPLONA',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Carrera 2 #30A - 89 sur. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'En Pamplona Maiporé es el lugar donde tu proyecto de vida empieza a hacerse realidad. Disfruta de apartamentos funcionales, completas zonas comunes y una ubicación estratégica en Soacha, con excelente conexión a Bogotá.',
        'modelo': 'C',
        'area_construida': '59,05',
        'area_privada': '51,2',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'PAMPLONA',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Carrera 2 #30A - 89 sur. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'En Pamplona Maiporé es el lugar donde tu proyecto de vida empieza a hacerse realidad. Disfruta de apartamentos funcionales, completas zonas comunes y una ubicación estratégica en Soacha, con excelente conexión a Bogotá.',
        'modelo': 'D',
        'area_construida': '63,49',
        'area_privada': '55,89',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'ZARZAL',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 30A sur #2 - 201, Soacha, Autopista Sur, sentido sur-norte, frente a Alfagres',
        'descripcion': 'Vive en Zarzal, un proyecto que combina diseño moderno y sostenible a pocos minutos de Bogotá y con vías de fácil acceso. Ubicado en el sector de mayor valorización de Soacha, con zonas verdes y espacios sociales pensados para disfrutar en familia',
        'modelo': 1,
        'area_construida': '43,3',
        'area_privada': '38,51',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'ZARZAL',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 30A sur #2 - 201, Soacha, Autopista Sur, sentido sur-norte, frente a Alfagres',
        'descripcion': 'Vive en Zarzal, un proyecto que combina diseño moderno y sostenible a pocos minutos de Bogotá y con vías de fácil acceso. Ubicado en el sector de mayor valorización de Soacha, con zonas verdes y espacios sociales pensados para disfrutar en familia',
        'modelo': 2,
        'area_construida': '39,06',
        'area_privada': '34,89',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'LA MACARENA',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Carrera 1 #31A sur - 72. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'Vivir en La Macarena Maiporé significa estar cerca de colegio, comercio y el futuro portal de TransMilenio, facilitando tu movilidad y el día a día. Además, cuenta con zonas sociales y espacios para compartir, descansar y disfrutar en comunidad.',
        'modelo': 'A',
        'area_construida': '38,78',
        'area_privada': '34,42',
        'habitaciones': 2,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'LA MACARENA',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Carrera 1 #31A sur - 72. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'Vivir en La Macarena Maiporé significa estar cerca de colegio, comercio y el futuro portal de TransMilenio, facilitando tu movilidad y el día a día. Además, cuenta con zonas sociales y espacios para compartir, descansar y disfrutar en comunidad.',
        'modelo': 'B',
        'area_construida': '34,94',
        'area_privada': '31,33',
        'habitaciones': 2,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'MONGUI',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 31 sur #0-143 este. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'Monguí Maiporé ofrece variedad de zonas sociales, pensadas para el descanso, la recreación y el disfrute en comunidad, diseñado para mayor comodidad, bienestar y calidad de vida de las familias.',
        'modelo': 'A',
        'area_construida': '56,29',
        'area_privada': '50,41',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'MONGUI',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 31 sur #0-143 este. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'Monguí Maiporé ofrece variedad de zonas sociales, pensadas para el descanso, la recreación y el disfrute en comunidad, diseñado para mayor comodidad, bienestar y calidad de vida de las familias.',
        'modelo': 'B',
        'area_construida': '51,41',
        'area_privada': '46,31',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'MONGUI',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 31 sur #0-143 este. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'Monguí Maiporé ofrece variedad de zonas sociales, pensadas para el descanso, la recreación y el disfrute en comunidad, diseñado para mayor comodidad, bienestar y calidad de vida de las familias.',
        'modelo': 'C',
        'area_construida': '45,05',
        'area_privada': '40,55',
        'habitaciones': 1,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'MONGUI',
        'tipo': 'VIS',
        'municipio': 'Soacha',
        'ubicacion': 'Ciudadela Maiporé',
        'direccion': 'Calle 31 sur #0-143 este. Ciudadela Colsubsidio Maiporé - Soacha',
        'descripcion': 'Monguí Maiporé ofrece variedad de zonas sociales, pensadas para el descanso, la recreación y el disfrute en comunidad, diseñado para mayor comodidad, bienestar y calidad de vida de las familias.',
        'modelo': 'D',
        'area_construida': '56,27',
        'area_privada': '50,44',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'BOSQUE DE ARRAYÁN',
        'tipo': 'VIS',
        'municipio': 'Tocancipá',
        'ubicacion': 'Tocancipá',
        'direccion': 'Carrera 9f #2 sur - 26. Tocancipá, Cundinamarca',
        'descripcion': 'Bosque de Arrayán está pensado para que más familias puedan cumplir el sueño de tener vivienda propia en un entorno tranquilo, seguro y rodeado de naturaleza. Combina accesibilidad, sostenibilidad y calidad de vida, convirtiéndose en una opción responsable y confiable para construir un mejor futuro familiar.',
        'modelo': 'D',
        'area_construida': '48,05',
        'area_privada': '43,53',
        'habitaciones': 2,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'BOSQUE DE ARRAYÁN',
        'tipo': 'VIS',
        'municipio': 'Tocancipá',
        'ubicacion': 'Tocancipá',
        'direccion': 'Carrera 9f #2 sur - 26. Tocancipá, Cundinamarca',
        'descripcion': 'Bosque de Arrayán está pensado para que más familias puedan cumplir el sueño de tener vivienda propia en un entorno tranquilo, seguro y rodeado de naturaleza. Combina accesibilidad, sostenibilidad y calidad de vida, convirtiéndose en una opción responsable y confiable para construir un mejor futuro familiar.',
        'modelo': 'E',
        'area_construida': '58,22',
        'area_privada': '52,21',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'BOSQUE DE ARRAYÁN',
        'tipo': 'VIS',
        'municipio': 'Tocancipá',
        'ubicacion': 'Tocancipá',
        'direccion': 'Carrera 9f #2 sur - 26. Tocancipá, Cundinamarca',
        'descripcion': 'Bosque de Arrayán está pensado para que más familias puedan cumplir el sueño de tener vivienda propia en un entorno tranquilo, seguro y rodeado de naturaleza. Combina accesibilidad, sostenibilidad y calidad de vida, convirtiéndose en una opción responsable y confiable para construir un mejor futuro familiar.',
        'modelo': 'F',
        'area_construida': '58,9',
        'area_privada': '53,07',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'BOSQUE DE TURPIAL',
        'tipo': 'VIS',
        'municipio': 'Tocancipá',
        'ubicacion': 'Tocancipá',
        'direccion': 'Calle 2 #9F - 32. Tocancipá, Cundinamarca',
        'descripcion': 'Bosque de Turpial ofrece un estilo de vida cómodo y accesible, perfecto para aquellos que buscan una vivienda de calidad sin sacrificar la comodidad ni el medio ambiente.',
        'modelo': 'A',
        'area_construida': 47,
        'area_privada': '42,86',
        'habitaciones': 1,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'BOSQUE DE TURPIAL',
        'tipo': 'VIS',
        'municipio': 'Tocancipá',
        'ubicacion': 'Tocancipá',
        'direccion': 'Calle 2 #9F - 32. Tocancipá, Cundinamarca',
        'descripcion': 'Bosque de Turpial ofrece un estilo de vida cómodo y accesible, perfecto para aquellos que buscan una vivienda de calidad sin sacrificar la comodidad ni el medio ambiente.',
        'modelo': 'B',
        'area_construida': '57,52',
        'area_privada': '52,33',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'BOSQUE DE TURPIAL',
        'tipo': 'VIS',
        'municipio': 'Tocancipá',
        'ubicacion': 'Tocancipá',
        'direccion': 'Calle 2 #9F - 32. Tocancipá, Cundinamarca',
        'descripcion': 'Bosque de Turpial ofrece un estilo de vida cómodo y accesible, perfecto para aquellos que buscan una vivienda de calidad sin sacrificar la comodidad ni el medio ambiente.',
        'modelo': 'C',
        'area_construida': '57,52',
        'area_privada': '53,33',
        'habitaciones': 2,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'BOSQUE DE TURPIAL',
        'tipo': 'VIS',
        'municipio': 'Tocancipá',
        'ubicacion': 'Tocancipá',
        'direccion': 'Calle 2 #9F - 32. Tocancipá, Cundinamarca',
        'descripcion': 'Bosque de Turpial ofrece un estilo de vida cómodo y accesible, perfecto para aquellos que buscan una vivienda de calidad sin sacrificar la comodidad ni el medio ambiente.',
        'modelo': 'D',
        'area_construida': '57,52',
        'area_privada': '52,55',
        'habitaciones': 2,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'INARI',
        'tipo': 'VIS',
        'municipio': 'Chía',
        'ubicacion': 'Chía',
        'direccion': 'Calle 12 #2 - 125. Barrio 20 Julio, Chía, Cundinamarca',
        'descripcion': 'Inari ofrece espacios funcionales, ideales para comenzar una nueva etapa o invertir inteligentemente. Ubicado en Chía, en una zona de alto crecimiento y excelente infraestructura.',
        'modelo': 'A',
        'area_construida': '44,73',
        'area_privada': '40,66',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'INARI',
        'tipo': 'VIS',
        'municipio': 'Chía',
        'ubicacion': 'Chía',
        'direccion': 'Calle 12 #2 - 125. Barrio 20 Julio, Chía, Cundinamarca',
        'descripcion': 'Inari ofrece espacios funcionales, ideales para comenzar una nueva etapa o invertir inteligentemente. Ubicado en Chía, en una zona de alto crecimiento y excelente infraestructura.',
        'modelo': 'B',
        'area_construida': '41,6',
        'area_privada': '38,15',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'INARI',
        'tipo': 'VIS',
        'municipio': 'Chía',
        'ubicacion': 'Chía',
        'direccion': 'Calle 12 #2 - 125. Barrio 20 Julio, Chía, Cundinamarca',
        'descripcion': 'Inari ofrece espacios funcionales, ideales para comenzar una nueva etapa o invertir inteligentemente. Ubicado en Chía, en una zona de alto crecimiento y excelente infraestructura.',
        'modelo': 'C',
        'area_construida': '34,7',
        'area_privada': '31,77',
        'habitaciones': 2,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'RESERVA DE AGUAYACÁN',
        'tipo': 'VIS',
        'municipio': 'Girardot',
        'ubicacion': 'Girardot',
        'direccion': 'Calle 35A # 24-99. Girardot, Cundinamarca',
        'descripcion': 'Reserva de Guayacán cuenta con apartamentos diseñados para ofrecer ventilación óptima, un clima cálido y vista a un entorno natural único.',
        'modelo': 'A',
        'area_construida': '52,98',
        'area_privada': '46,98',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '135 SMMLV',
    },
    {
        'proyecto': 'RESERVA DE AGUAYACÁN',
        'tipo': 'VIS',
        'municipio': 'Girardot',
        'ubicacion': 'Girardot',
        'direccion': 'Calle 35A # 24-99. Girardot, Cundinamarca',
        'descripcion': 'Reserva de Guayacán cuenta con apartamentos diseñados para ofrecer ventilación óptima, un clima cálido y vista a un entorno natural único.',
        'modelo': 'B',
        'area_construida': '43,53',
        'area_privada': '38,24',
        'habitaciones': 1,
        'banos': 1,
        'valor_vis': '135 SMMLV',
    },
    {
        'proyecto': 'RESERVA DE AGUAYACÁN',
        'tipo': 'VIS',
        'municipio': 'Girardot',
        'ubicacion': 'Girardot',
        'direccion': 'Calle 35A # 24-99. Girardot, Cundinamarca',
        'descripcion': 'Reserva de Guayacán cuenta con apartamentos diseñados para ofrecer ventilación óptima, un clima cálido y vista a un entorno natural único.',
        'modelo': 'C',
        'area_construida': '53,41',
        'area_privada': '47,11',
        'habitaciones': 1,
        'banos': 2,
        'valor_vis': '135 SMMLV',
    },
    {
        'proyecto': 'SAMÁN',
        'tipo': 'VIS',
        'municipio': 'Ricaurte',
        'ubicacion': 'Ricaurte',
        'direccion': 'Calle 7a #18-108. Ricaurte, Cundinamarca',
        'descripcion': 'Vivir en Samán es seguir compartiendo en familia mientras cumples tus sueños en una ubicación privilegiada y tranquila.',
        'modelo': 'A',
        'area_construida': '52,53',
        'area_privada': '44,19',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '135 SMMLV',
    },
    {
        'proyecto': 'PAYANDÉ',
        'tipo': 'VIS',
        'municipio': 'Ricaurte',
        'ubicacion': 'Ricaurte',
        'direccion': 'Calle 7 #18 - 108. Ricaurte, Cundinamarca',
        'descripcion': 'Payandé es el hogar ideal para aquellos que buscan lo mejor para sus seres queridos. Aquí las mañanas llenas de sol, las tardes de juegos en familia y los momentos de descanso en la naturaleza se hacen realidad.',
        'modelo': 3,
        'area_construida': '56,86',
        'area_privada': '47,01',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '135 SMMLV',
    },
    {
        'proyecto': 'PAYANDÉ',
        'tipo': 'VIS',
        'municipio': 'Ricaurte',
        'ubicacion': 'Ricaurte',
        'direccion': 'Calle 7 #18 - 108. Ricaurte, Cundinamarca',
        'descripcion': 'Payandé es el hogar ideal para aquellos que buscan lo mejor para sus seres queridos. Aquí las mañanas llenas de sol, las tardes de juegos en familia y los momentos de descanso en la naturaleza se hacen realidad.',
        'modelo': 4,
        'area_construida': 44,
        'area_privada': '38,89',
        'habitaciones': 2,
        'banos': 1,
        'valor_vis': '135 SMMLV',
    },
    {
        'proyecto': 'VIBO ONCE',
        'tipo': 'VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Centro',
        'direccion': 'Carrera 14 #3-58',
        'descripcion': 'Vivo Once es vivir el renacer del centro con diseño, conexión y bienestar. Ubicado en una de las zonas de mayor transformación urbana de Bogotá',
        'modelo': 'A',
        'area_construida': '50,44',
        'area_privada': '43,12',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'VIBO ONCE',
        'tipo': 'VIS',
        'municipio': 'VIS',
        'ubicacion': 'Centro',
        'direccion': 'Carrera 14 #3-58',
        'descripcion': 'Vivo Once es vivir el renacer del centro con diseño, conexión y bienestar. Ubicado en una de las zonas de mayor transformación urbana de Bogotá',
        'modelo': 'B2',
        'area_construida': '42,03',
        'area_privada': '36,74',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'KARAKALI',
        'tipo': 'VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Chapinero',
        'direccion': 'Carrera 15 #63A-22. Bogotá',
        'descripcion': 'Vive en Chapinero, una de las zonas más estratégicas de la ciudad, rodeada de universidades, comercio y conectividad. Este innovador proyecto de apartaestudios combina el concepto de coliving y coworking, creando espacios modernos que se adaptan a tu estilo de vida.',
        'modelo': 1,
        'area_construida': '28,01',
        'area_privada': '24,11',
        'habitaciones': 1,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'KARAKALI',
        'tipo': 'VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Chapinero',
        'direccion': 'Carrera 15 #63A-22. Bogotá',
        'descripcion': 'Vive en Chapinero, una de las zonas más estratégicas de la ciudad, rodeada de universidades, comercio y conectividad. Este innovador proyecto de apartaestudios combina el concepto de coliving y coworking, creando espacios modernos que se adaptan a tu estilo de vida.',
        'modelo': 2,
        'area_construida': '28,97',
        'area_privada': '23,86',
        'habitaciones': 1,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'KARAKALI',
        'tipo': 'VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Chapinero',
        'direccion': 'Carrera 15 #63A-22. Bogotá',
        'descripcion': 'Vive en Chapinero, una de las zonas más estratégicas de la ciudad, rodeada de universidades, comercio y conectividad. Este innovador proyecto de apartaestudios combina el concepto de coliving y coworking, creando espacios modernos que se adaptan a tu estilo de vida.',
        'modelo': 3,
        'area_construida': '26,05',
        'area_privada': '21,6',
        'habitaciones': 1,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'ARAUCARIA',
        'tipo': 'NO VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Ciudadela calle 80',
        'direccion': 'Diagonal 86A #111A',
        'descripcion': 'Apartamentos con acabados de alta calidad, parqueadero privado y depósito, pensados para brindarte el confort que mereces. Combina diseño contemporáneo, funcionalidad y bienestar en cada rincón.',
        'modelo': 'C',
        'area_construida': '74,36',
        'area_privada': '68,06',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'ARAUCARIA',
        'tipo': 'NO VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Ciudadela calle 80',
        'direccion': 'Diagonal 86A #111A',
        'descripcion': 'Apartamentos con acabados de alta calidad, parqueadero privado y depósito, pensados para brindarte el confort que mereces. Combina diseño contemporáneo, funcionalidad y bienestar en cada rincón.',
        'modelo': 'B',
        'area_construida': '86,93',
        'area_privada': '80,14',
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'ARAUCARIA',
        'tipo': 'NO VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Ciudadela calle 80',
        'direccion': 'Calle 86A #111A. Ciudadela Colsubsidio Calle 80',
        'descripcion': 'Apartamentos con acabados de alta calidad, parqueadero privado y depósito, pensados para brindarte el confort que mereces. Combina diseño contemporáneo, funcionalidad y bienestar en cada rincón.',
        'modelo': 'A1',
        'area_construida': '105,4',
        'area_privada': '97,15',
        'habitaciones': 3,
        'banos': 3,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'LOS NOGALES',
        'tipo': 'NO VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Ciudadela calle 80',
        'direccion': 'Calle 83 #111A-41. Ciudadela Colsubsidio Calle 80',
        'descripcion': 'Apartamentos con terminaciones de alta calidad, parqueadero privado y depósito, diseñados para ofrecerte el confort que mereces. Cada espacio integra diseño contemporáneo, funcionalidad y bienestar en perfecta armonía',
        'modelo': 'A1',
        'area_construida': 74,
        'area_privada': 67,
        'habitaciones': 3,
        'banos': 2,
        'valor_vis': None,
    },
    {
        'proyecto': 'ABETO',
        'tipo': 'NO VIS',
        'municipio': 'Bogota',
        'ubicacion': 'Ciudadela calle 80',
        'direccion': None,
        'descripcion': 'Este proyecto está pensado para futuros propietarios, ofreciendo un espacio ideal para comenzar una nueva etapa de vida, donde la naturaleza y la ciudad conviven en armonía.',
        'modelo': None,
        'area_construida': 37,
        'area_privada': None,
        'habitaciones': 1,
        'banos': 1,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'LA ARBOLEDA',
        'tipo': 'VIS',
        'municipio': 'Bogota',
        'ubicacion': 'San Cristobal Sur',
        'direccion': 'Carrera 15 Este #47-02 Sur',
        'descripcion': 'Junto al patio de SITP Estación Gaviotas',
        'modelo': None,
        'area_construida': '39,96',
        'area_privada': None,
        'habitaciones': None,
        'banos': None,
        'valor_vis': '150 SMMLV',
    },
    {
        'proyecto': 'VERDE ESPERANZA',
        'tipo': 'NO VIS',
        'municipio': 'Ubate',
        'ubicacion': 'Ubate',
        'direccion': 'Carrera 7 #8-12, Ubaté - Villa de San Diego. Cundinamarca',
        'descripcion': 'Vive rodeado de entorno natural con amplios espacios verdes, pensados para tu comodidad.',
        'modelo': 'A',
        'area_construida': '49,53',
        'area_privada': '46,13',
        'habitaciones': 2,
        'banos': 2,
        'valor_vis': '135 SMMLV',
    },
]


# ── Afiliados (fabricated; the source `Afiliados Colsubsidio` sheet has zero
#    data rows) ──────────────────────────────────────────────────────────────
# Distribution: every categoria_afiliado (A/B/C) and every one of the six
# credit bands (Excelente / Muy Bueno / Bueno / Aceptable / Regular / Malo) is
# covered; at least one row carries ha_recibido_subsidio=True.
#
# Demo stars (listed in the README for juror demos):
#   CC 1010101010  Andrea Marín  — A, 880 (Excelente)
#   CC 2020202020  Beto Salazar — B, 720 (Bueno)
#   CC 3030303030  Camila Ríos  — C, 580 (Regular)
AFILIADOS: list[dict] = [
    {"tipo_documento": "CC", "numero_documento": "1010101010", "nombre_apellido": "Andrea Marín",
     "fecha_nacimiento": date(1990, 3, 15), "estado_civil": "soltero",
     "salario_base_cotizacion": Decimal("4500000"), "categoria": "A", "categoria_afiliado": "A",
     "score_credito": 880, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "2020202020", "nombre_apellido": "Beto Salazar",
     "fecha_nacimiento": date(1985, 6, 20), "estado_civil": "casado",
     "salario_base_cotizacion": Decimal("3200000"), "categoria": "B", "categoria_afiliado": "B",
     "score_credito": 720, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "3030303030", "nombre_apellido": "Camila Ríos",
     "fecha_nacimiento": date(1995, 11, 30), "estado_civil": "union_libre",
     "salario_base_cotizacion": Decimal("1800000"), "categoria": "C", "categoria_afiliado": "C",
     "score_credito": 580, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "4040404040", "nombre_apellido": "Diana López",
     "fecha_nacimiento": date(1988, 1, 10), "estado_civil": "casado",
     "salario_base_cotizacion": Decimal("5000000"), "categoria": "A", "categoria_afiliado": "A",
     "score_credito": 770, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "5050505050", "nombre_apellido": "Eduardo Páez",
     "fecha_nacimiento": date(1992, 9, 5), "estado_civil": "soltero",
     "salario_base_cotizacion": Decimal("2900000"), "categoria": "B", "categoria_afiliado": "B",
     "score_credito": 680, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "6060606060", "nombre_apellido": "Florencia Ruiz",
     "fecha_nacimiento": date(2000, 4, 22), "estado_civil": "divorciado",
     "salario_base_cotizacion": Decimal("1500000"), "categoria": "C", "categoria_afiliado": "C",
     "score_credito": 420, "ha_recibido_subsidio": True},
    {"tipo_documento": "CC", "numero_documento": "7070707070", "nombre_apellido": "Gonzalo Tamayo",
     "fecha_nacimiento": date(1979, 12, 1), "estado_civil": "casado",
     "salario_base_cotizacion": Decimal("4200000"), "categoria": "A", "categoria_afiliado": "A",
     "score_credito": 650, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "8080808080", "nombre_apellido": "Hugo Mendoza",
     "fecha_nacimiento": date(1991, 7, 18), "estado_civil": "union_libre",
     "salario_base_cotizacion": Decimal("3600000"), "categoria": "B", "categoria_afiliado": "B",
     "score_credito": 750, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "9090909090", "nombre_apellido": "Irene Castro",
     "fecha_nacimiento": date(1996, 2, 14), "estado_civil": "soltero",
     "salario_base_cotizacion": Decimal("1700000"), "categoria": "C", "categoria_afiliado": "C",
     "score_credito": 510, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "1111111111", "nombre_apellido": "Jorge Vargas",
     "fecha_nacimiento": date(1983, 5, 25), "estado_civil": "casado",
     "salario_base_cotizacion": Decimal("6000000"), "categoria": "A", "categoria_afiliado": "A",
     "score_credito": 920, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "1212121212", "nombre_apellido": "Laura Gómez",
     "fecha_nacimiento": date(1990, 10, 11), "estado_civil": "divorciado",
     "salario_base_cotizacion": Decimal("3100000"), "categoria": "B", "categoria_afiliado": "B",
     "score_credito": 700, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "1313131313", "nombre_apellido": "Marcos Silva",
     "fecha_nacimiento": date(1998, 8, 8), "estado_civil": "separado",
     "salario_base_cotizacion": Decimal("1600000"), "categoria": "C", "categoria_afiliado": "C",
     "score_credito": 590, "ha_recibido_subsidio": True},
    {"tipo_documento": "CC", "numero_documento": "1414141414", "nombre_apellido": "Natalia Reyes",
     "fecha_nacimiento": date(1987, 3, 30), "estado_civil": "union_libre",
     "salario_base_cotizacion": Decimal("4800000"), "categoria": "A", "categoria_afiliado": "A",
     "score_credito": 810, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "1515151515", "nombre_apellido": "Óscar Torres",
     "fecha_nacimiento": date(2001, 12, 15), "estado_civil": "soltero",
     "salario_base_cotizacion": Decimal("2200000"), "categoria": "B", "categoria_afiliado": "B",
     "score_credito": 460, "ha_recibido_subsidio": False},
    {"tipo_documento": "CC", "numero_documento": "1616161616", "nombre_apellido": "Patricia Núñez",
     "fecha_nacimiento": date(1993, 6, 7), "estado_civil": "casado",
     "salario_base_cotizacion": Decimal("1900000"), "categoria": "C", "categoria_afiliado": "C",
     "score_credito": 670, "ha_recibido_subsidio": False},
]


# ── Parsers ────────────────────────────────────────────────────────────────
def _num(v: object) -> Decimal | None:
    """Parse a source area cell to Decimal; int/float/str-with-comma -> Decimal; None -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    s = str(v).strip().replace(",", ".")
    return Decimal(s) if s else None


def _modelo(v: object) -> str:
    """modelo: blank -> '' (NOT NULL DEFAULT ''); int/str -> str(v)."""
    return "" if v is None else str(v)


def _proyecto_row(raw: dict) -> dict:
    return {
        "proyecto": raw["proyecto"],
        "tipo": raw["tipo"],
        "municipio": raw["municipio"],
        "ubicacion": raw["ubicacion"],
        "direccion": raw["direccion"],
        "descripcion": raw["descripcion"],
        "modelo": _modelo(raw["modelo"]),
        "area_construida_m2": _num(raw["area_construida"]),
        "area_privada_m2": _num(raw["area_privada"]),
        "cantidad_habitaciones": raw["habitaciones"],
        "cantidad_banos": raw["banos"],
        "valor_vis_smmlv": raw["valor_vis"],
    }


async def _seed_proyectos(session) -> tuple[int, int]:
    """Insert 44 proyectos with ON CONFLICT (proyecto, modelo) DO NOTHING.

    Returns (newly_inserted, total_count_after_insert).
    """
    rows = [_proyecto_row(r) for r in PROYECTOS_RAW]
    stmt = (
        pg_insert(ProyectoColsubsidioEntity)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["proyecto", "modelo"])
    )
    result = await session.execute(stmt)
    # psycopg3 reports -1 rowcount for INSERT ... ON CONFLICT DO NOTHING, so the
    # "newly inserted" figure is unreliable; re-count from the table instead
    # and report inserted as None (the `total` is what idempotency asserts on).
    _ = result.rowcount  # consumed for logging only; -1 is expected
    total = (
        await session.execute(text("select count(*) from proyectos_colsubsidio"))
    ).scalar_one()
    return None, int(total)


async def _seed_afiliados(session) -> tuple[int, int]:
    """Replace the seed afiliado set (DELETE WHERE is_seed=true then re-INSERT).

    Returns (inserted_seed_count, seed_total_after_insert).
    """
    await session.execute(
        delete(AfiliadoColsubsidioEntity).where(AfiliadoColsubsidioEntity.is_seed.is_(True))
    )
    objs = [AfiliadoColsubsidioEntity(is_seed=True, **a) for a in AFILIADOS]
    session.add_all(objs)
    await session.flush()
    total = (
        await session.execute(
            text("select count(*) from afiliados_colsubsidio where is_seed = true")
        )
    ).scalar_one()
    return len(objs), int(total)


async def _run() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logger.info("seed_colsubsidio.start")
    try:
        async with AsyncSessionLocal() as session:
            _, p_total = await _seed_proyectos(session)
            a_ins, a_total = await _seed_afiliados(session)
            await session.commit()
        logger.info(
            "seed_colsubsidio.done — proyectos total=%s, afiliados inserted=%s seed_total=%s",
            p_total, a_ins, a_total,
        )
        return 0
    except Exception:
        logger.exception("seed_colsubsidio.failed")
        return 1


def main() -> int:
    async def _wrap() -> int:
        try:
            return await _run()
        finally:
            await engine.dispose()

    return asyncio.run(_wrap())


if __name__ == "__main__":
    sys.exit(main())