//! Automatic final receipts from the actual native receiving input only.
use super::*;

impl Messaging {
    pub(crate) fn confirm_received_dot(&mut self) {
        let mut waiting = self.journal.receipt_pending();
        if waiting.is_empty() {
            return;
        }
        let count = waiting.len();
        waiting.rotate_left(self.receipt_cursor % count);
        self.receipt_cursor = (self.receipt_cursor + 8) % count;
        for message in waiting.into_iter().take(8) {
            let Ok(Some(input)) = self.clients.received_input(
                &message.to.session_id,
                &message.request_id,
                &message.fingerprint,
            ) else {
                continue;
            };
            if input.thread() != message.to.session_id
                || input.request() != message.id
                || input.turn().is_empty()
                || transcript::fingerprint(input.text()) != message.fingerprint
            {
                continue;
            }
            let Some(challenge) = receipt_challenge(input.text(), &message.id) else {
                continue;
            };
            if !self.journal.reserve_receipt(&message.id) {
                continue;
            }
            // This is the native owner's observed input, not a fabricated MCP
            // caller or a queue/RPC acknowledgement. The sidecar independently
            // checks the challenge and original receiving thread.
            let result = self.dot.call(
                "confirm",
                json!({"id":message.id,
                "source":format!("codex:{}", input.thread()), "deliveryChallenge":challenge}),
            );
            if result.is_ok_and(|value| value["recipientConfirmed"] == true) {
                if let Some(row) = self.journal.messages_mut().find(|row| row.id == message.id) {
                    row.answered = true;
                }
                self.journal.save();
            }
        }
    }
}

fn receipt_challenge<'a>(text: &'a str, id: &str) -> Option<&'a str> {
    let prefix = format!("[Agent HUD delivery receipt: only after actually receiving this input, call confirm_delivery with id {id} and delivery_challenge ");
    let footer = text.lines().last()?.strip_prefix(&prefix)?;
    let (challenge, rest) = footer.split_once(". Use the challenge only for confirmation;")?;
    (!rest.is_empty()
        && (16..=256).contains(&challenge.len())
        && challenge
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_'))
    .then_some(challenge)
}
