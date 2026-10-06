/**
 * Libellés des refus d'adresse serveur. Module à part pour que l'écran de
 * connexion (chunk d'entrée) n'importe pas toute la vue Application et, par
 * chaîne, la configuration et la bibliothèque (task d5c1183f).
 */
import type { ServerOriginRefusal } from "./platform";

/** Words for the machine codes the shell answers when it refuses an address. */
export function originRefusalMessage(reason: ServerOriginRefusal): string {
  switch (reason) {
    case "origin_empty":
      return "Saisissez l'adresse du serveur, par exemple https://studio.exemple.com.";
    case "origin_too_long":
      return "Cette adresse est trop longue.";
    case "origin_invalid":
      return "Cette adresse n'est pas valide. Format attendu : https://studio.exemple.com.";
    case "origin_unsupported_scheme":
      return "Seules les adresses https:// sont acceptées (http:// uniquement pour localhost en développement).";
    case "origin_credentials_not_allowed":
      return "L'adresse ne doit contenir ni identifiant ni mot de passe.";
    case "origin_not_an_origin":
      return "Indiquez uniquement l'adresse du serveur, sans chemin, paramètre ni ancre.";
    case "origin_insecure_scheme":
      return "Une adresse http:// n'est acceptée que pour localhost ou 127.0.0.1. Utilisez https://.";
    case "origin_is_desktop_origin":
      return "Cette adresse est celle de l'application elle-même, pas celle du serveur Studio OS.";
    case "storage_unavailable":
    case "storage_failed":
      return "L'adresse n'a pas pu être enregistrée sur ce poste.";
    case "unavailable":
      return "Cette commande n'est disponible que dans l'application Desktop.";
    default:
      return "L'adresse n'a pas pu être enregistrée.";
  }
}
