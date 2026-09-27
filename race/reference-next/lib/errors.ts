// Shared error types. This file is complete; you do not need to change it.

/** Thrown when input fails validation (bad amount, bad date, unknown category, ...). */
export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

/** Thrown when an id does not exist in the store. */
export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotFoundError";
  }
}
