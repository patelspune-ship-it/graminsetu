export async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);

  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
      signal: controller.signal,
    });

    const body = await response.json().catch(() => null);

    if (!response.ok) {
      const detail = body?.detail;

      const message = Array.isArray(detail)
        ? detail
            .map((item) => `${item.loc?.slice(1).join(".")}: ${item.msg}`)
            .join("; ")
        : typeof detail === "string"
          ? detail
          : `Request failed (${response.status}).`;

      throw new Error(message);
    }

    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The server took too long. Please try again.");
    }

    if (error instanceof TypeError) {
      throw new Error(
        "Cannot reach the backend. Check that FastAPI is running."
      );
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

// Parse decimal text using integer operations, never parseFloat.
export function rupeesToPaise(input) {
  const value = String(input).trim();

  if (!/^\d{1,9}(\.\d{1,2})?$/.test(value)) {
    throw new Error(
      "Enter capital as a number with up to two decimal places, without commas."
    );
  }

  const [rupees, fraction = ""] = value.split(".");
  const paise =
    BigInt(rupees) * 100n +
    BigInt(fraction.padEnd(2, "0"));

  if (paise > 10_000_000_000n) {
    throw new Error("Capital exceeds the supported MVP limit of ₹10 crore.");
  }

  // This limit is well below JavaScript's maximum safe integer.
  return Number(paise);
}

export function formatMoney(paise) {
  const amount = BigInt(paise);
  const rupees = amount / 100n;
  const fraction = amount % 100n;

  const formatted = new Intl.NumberFormat("en-IN").format(rupees);

  return `₹${formatted}${
    fraction ? `.${fraction.toString().padStart(2, "0")}` : ""
  }`;
}
