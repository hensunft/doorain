import { describe, expect, it } from 'vitest'
import { validate } from './RegisterPage'

const ok = { code: 'abc', username: 'ivan.p', first: 'Иван', last: 'Петров-Водкин', email: 'ivan@example.com', password: 'long passphrase 1', repeat: 'long passphrase 1', terms: true, pd: true }

describe('проверка формы регистрации', () => {
  it('корректная форма проходит', () => expect(validate(ok)).toEqual({}))
  it('повтор пароля, почта, имя и согласия проверяются', () => {
    const e = validate({ ...ok, repeat: 'другой', email: 'нет', first: 'Иван1', terms: false, pd: false })
    expect(Object.keys(e).sort()).toEqual(['email', 'first', 'pd', 'repeat', 'terms'])
  })
  it('короткий пароль и неверный логин', () => {
    expect(Object.keys(validate({ ...ok, password: 'short', repeat: 'short', username: 'a b' })).sort()).toEqual(['password', 'username'])
  })
})
