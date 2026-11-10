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
        let sent = dot::control("send", json!({"id":id,"source":source,"text":text}));
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
            from: party(host.snapshot, &caller.client, &caller.session_id),
            to: Party {
                client: "dot".into(),
                session_id: dot::SESSION.into(),
                title: Some("Luo".into()),
            },
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
        Ok(
            json!({"id":id,"state":state,"reason":reason,"pass":count,"actualReceiptConfirmed":false}),
        )
    }

    pub(crate) fn get_dot(&self, message: &Message) -> Result<Value> {
        let mut value = dot::control(
            "get",
            json!({"id":message.id,
            "source":format!("codex:{}",message.from.session_id)}),
        )?;
        value["to"] = json!({"client":"dot","sessionId":dot::SESSION,"title":"Luo"});
        value["reply"] = value["replyId"].clone();
        value["answer"] = value["replyText"].clone();
        value["actualReceiptConfirmed"] = value["recipientConfirmed"].clone();
        Ok(value)
    }

    pub(crate) fn confirm_dot(&mut self, caller: &Caller, id: &str) -> Result<Value> {
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
        let result = dot::control(
            "confirm",
            json!({"id":id,"source":format!("codex:{}",caller.session_id)}),
        )?;
        if result["recipientConfirmed"] == true {
            if let Some(message) = self.journal.messages_mut().find(|message| message.id == id) {
                message.answered = true;
            }
            self.journal.save();
        }
        Ok(result)
    }

    pub(crate) fn maintain_dot(&mut self, host: &Host<'_>, now: i64) {
        if !self.preferences.enabled || !dot::enabled() {
            return;
        }
        let Ok(value) = dot::control("pending", json!({})) else {
            return;
        };
        let Some(rows) = value["messages"].as_array() else {
            return;
        };
        for row in rows.iter().take(8) {
            let Some(id) = row["id"].as_str() else {
                continue;
            };
            let Some(parent) = self.journal.find(id).cloned() else {
                continue;
            };
            if parent.to.client != "dot"
                || parent.from.client != "codex"
                || row["source"] != format!("codex:{}", parent.from.session_id)
            {
                continue;
            }
            let Ok(claim) = dot::control("claim", json!({"id":id})) else {
                continue;
            };
            if claim["claimed"] != true {
                continue;
            }
            let Some(reply_id) = claim["replyId"].as_str() else {
                continue;
            };
            let Some(text) = claim["text"].as_str() else {
                continue;
            };
            let delivered = format!(
                "[Agent HUD · Dot Luo; reply_to={id}; reply_id={reply_id}]\n{text}\n\n[Agent HUD delivery receipt: only after actually receiving this input, call confirm_delivery with id {reply_id}. This reports delivery to Luo; it does not send a chat reply. Do not acknowledge a delivery_receipt event.] "
            );
            let receipt = self.clients.send(SendRequest {
                provider: Provider::Codex,
                session_id: parent.from.session_id.clone(),
                request_id: reply_id.into(),
                text: delivered.clone(),
                form: PromptForm::Labelled,
                operation: Operation::Enqueue,
                expected_turn_id: None,
            });
            let (state, native) = match &receipt {
                Ok(receipt) => {
                    self.clients.delivered(
                        receipt,
                        &Caller {
                            client: "dot".into(),
                            session_id: dot::SESSION.into(),
                            turn_id: None,
                        }
                        .surface(),
                        now,
                    );
                    let state = delivered_or_refused(receipt.state);
                    let native = if state == "refused" {
                        "refused"
                    } else if state == "uncertain" {
                        "uncertain"
                    } else {
                        "accepted"
                    };
                    (state, json!({"state":native,"deliveryMode":state}))
                }
                Err(_) => ("uncertain", json!({"state":"uncertain"})),
            };
            // Completion failure never releases a claimed send for another attempt.
            let _ = dot::control("complete", json!({"id":id,"native":native}));
            self.journal.add(Message {
                id: reply_id.into(),
                kind: Kind::Send,
                chain: parent.chain.clone(),
                count: parent.count + 1,
                from: Party {
                    client: "dot".into(),
                    session_id: dot::SESSION.into(),
                    title: Some("Luo".into()),
                },
                to: parent.from.clone(),
                form: PromptForm::Labelled,
                reply_to: Some(id.into()),
                request_id: reply_id.into(),
                sent_at_ms: now,
                cursor: None,
                fingerprint: transcript::fingerprint(&delivered),
                state: state.into(),
                reason: None,
                turn: None,
                answered: false,
                replied_by: None,
            });
            if let Some(parent) = self.journal.messages_mut().find(|message| message.id == id) {
                parent.replied_by = Some(reply_id.into());
                parent.answered = true;
            }
            self.journal.save();
        }
        let _ = host; // Native delivery retains its existing local-client authorization.
    }
}
