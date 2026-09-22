/** Сегодня в формате YYYY-MM-DD по местному времени: toISOString() отдаёт UTC и до 03:00 по Москве возвращает вчерашнюю дату. */
export const todayISO = (): string => new Date().toLocaleDateString('sv-SE')
