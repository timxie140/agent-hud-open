//! A registered Dot is not a Codex session. Existing clients keep their routes.
use super::*;
use agent_hud_platform::dot;

impl Messaging {
    pub(crate) fn send_dot(
        &mut self,
        caller: &Caller,
        text: &str,
        reply_to: Option<&str>,
        replied: Option<&Message>,
        host: &Host<'_>,
        now: i64,
    ) -> Result<Value> {
        if caller.client != "codex" {
            return Ok(refused(
                "Dot currently accepts messages from identified Codex threads",
            ));
        }
        let (chain, count) = self.next_pass(caller, host, replied);
        if self.preferences.limit.is_some_and(|limit| count > limit) {
            return Ok(refused(&words::limit(
                language(host.snapshot),
                self.preferences.limit.unwrap_or(0),
            )));
        }
        let id = message_id();
        let source = format!("codex:{}", caller.session_id);
        let sender = party(host.snapshot, &caller.client, &caller.session_id);
        let recipient = Party {
            client: "dot".into(),
            session_id: dot::SESSION.into(),
            title: Some("Dot".into()),
        };
        let left = chain
            .as_deref()
            .map(|chain| self.left_of(chain, &caller.session_id))
            .unwrap_or_else(|| caller.session_id.clone());
        let sent = self
            .dot
            .call("send", json!({"id":id,"source":source,"text":text}));
        let (state, reason) = match sent {
            Ok(value) => (
                if value["state"] == "webhook_accepted" {
                    "queued"
                } else {
                    "uncertain"
                },
                None,
            ),
            Err(error) => ("refused", Some(error)),
        };
        self.journal.add(Message {
            id: id.clone(),
            kind: Kind::Send,
            chain: chain.unwrap_or_else(|| id.clone()),
            count,
            from: sender.clone(),
            to: recipient.clone(),
            form: self.form(),
            reply_to: reply_to.map(str::to_owned),
            request_id: id.clone(),
            sent_at_ms: now,
            cursor: None,
            fingerprint: transcript::fingerprint(text),
            state: state.into(),
            reason: reason.clone(),
            turn: None,
            answered: false,
            replied_by: None,
        });
        (self.fly)(flight(
            &sender,
            &recipient,
            same_session(&left, &caller.session_id),
            false,
            matches!(state, "refused" | "uncertain"),
        ));
        Ok(
            json!({"id":id,"state":state,"reason":reason,"pass":count,"actualReceiptConfirmed":false}),
        )
    }

    pub(crate) fn get_dot(&self, message: &Message) -> Result<Value> {
        let mut value = self.dot.call(
            "get",
            json!({"id":message.id,
            "source":format!("codex:{}",message.from.session_id)}),
        )?;
        value["to"] = json!({"client":"dot","sessionId":dot::SESSION,"title":"Dot"});
        value["reply"] = value["replyId"].clone();
        value["answer"] = value["replyText"].clone();
        value["actualReceiptConfirmed"] = value["recipientConfirmed"].clone();
        Ok(value)
    }

    pub(crate) fn confirm_dot(
        &mut self,
        caller: &Caller,
        id: &str,
        challenge: &str,
    ) -> Result<Value> {
        if caller.client != "codex" {
            return Err("Only the actual receiving Codex thread may confirm delivery".into());
        }
        if let Some(message) = self.journal.find(id) {
            if message.from.client != "dot"
                || !same_session(&message.to.session_id, &caller.session_id)
            {
                return Err("Only the actual receiving Codex thread may confirm delivery".into());
            }
        }
        // The durable sidecar also binds reply_id to its original recipient.
        // This survives a crash after native acceptance but before journal save.
        let result = self.dot.call(
            "confirm",
            json!({"id":id,"source":format!("codex:{}",caller.session_id),"deliveryChallenge":challenge}),
        )?;
        if result["recipientConfirmed"] == true {
            if let Some(message) = self.journal.messages_mut().find(|message| message.id == id) {
                message.answered = true;
            }
            self.journal.save();
        }
        Ok(result)
    }
}
