import { expect, test } from 'claude-code/testing'
import { register } from './index.ts'

// `claude plugin test` refuses a plugin with a module and no test file, so this
// holds the place until the fleet pane brings real tests.
test('the hooks module exports register', async () => {
  expect(typeof register).toBe('function')
})
