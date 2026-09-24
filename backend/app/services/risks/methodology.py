"""Таксономия тем и словарь стабильных типов риска.

Типы риска — закрытый словарь: дедупликация идёт по (risk_type, scope, семейство нормы), а не по заголовку.
Это экспериментальная методика: до проверки юристом (docs/risk-methodology.md).
"""

from __future__ import annotations

TOPICS: list[tuple[str, str]] = [
    ("info_security", "Информация и защита информации"),
    ("personal_data", "Персональные данные и биометрия"),
    ("kii", "Критическая информационная инфраструктура"),
    ("ai", "Искусственный интеллект"),
    ("esign", "Электронная подпись и цифровой документооборот"),
    ("ip_it", "Интеллектуальная собственность в IT"),
    ("internet_business", "Интернет-бизнес и реклама"),
    ("digital_assets", "Цифровые активы"),
    ("liability", "Ответственность"),
]
TOPIC_IDS = [t for t, _ in TOPICS]
TOPIC_TITLES = dict(TOPICS)

# risk_type -> (заголовок по умолчанию, тема, роли)
RISK_TYPES: dict[str, tuple[str, str]] = {
    "pd_no_policy": ("Не опубликована политика обработки ПДн", "personal_data"),
    "pd_no_consent": ("Обработка ПДн без надлежащего согласия", "personal_data"),
    "pd_localization": ("Первичная запись ПДн граждан РФ вне РФ", "personal_data"),
    "pd_cross_border": ("Трансграничная передача ПДн без соблюдения условий", "personal_data"),
    "pd_no_notification": ("Не направлено уведомление об обработке ПДн", "personal_data"),
    "pd_security_measures": ("Недостаточные меры защиты ПДн", "personal_data"),
    "biometrics": ("Обработка биометрических данных без оснований", "personal_data"),
    "info_security_measures": ("Нарушение требований защиты информации", "info_security"),
    "trade_secret_regime": ("Не введён режим коммерческой тайны", "info_security"),
    "kii_categorization": ("Не проведено категорирование объектов КИИ", "kii"),
    "kii_incident": ("Нарушение требований по инцидентам на объектах КИИ", "kii"),
    "ai_compliance": ("Несоблюдение требований к использованию ИИ", "ai"),
    "esign_validity": ("Юридическая сила электронного документа под вопросом", "esign"),
    "ip_ownership": ("Неурегулированы исключительные права на программу/код", "ip_it"),
    "ip_license": ("Использование программы без лицензии либо вне её условий", "ip_it"),
    "ad_marking": ("Не выполнена маркировка интернет-рекламы", "internet_business"),
    "foreign_platform": ("Требования к иностранным лицам в сети Интернет", "internet_business"),
    "digital_asset_ops": ("Операции с цифровыми активами вне допустимых режимов", "digital_assets"),
    "criminal_it": ("Риск ответственности по гл. 28 УК РФ", "liability"),
    "admin_it": ("Риск административной ответственности", "liability"),
    "other_legal": ("Иной правовой риск", "info_security"),
    # учебные (student): подтверждённые ошибки понимания
    "misconception": ("Подтверждённая ошибка понимания нормы", "info_security"),
}
RISK_TYPE_IDS = list(RISK_TYPES)

FACT_STATUS = ("yes", "no", "unknown")
RELATION_KINDS = ("follow_up_of", "evidences", "conditional")

DISCLAIMER = "Ответы носят информационный характер и не заменяют профессиональную юридическую помощь"
