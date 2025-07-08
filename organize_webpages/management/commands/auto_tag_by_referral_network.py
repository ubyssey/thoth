from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone

import asyncio
from asgiref.sync import async_to_sync, sync_to_async

import math
import re
import copy

from webpage.models import Domain, Referral
from organize_webpages.models import ThothTag

class Command(BaseCommand):
    help = "Remove and create tags by referral network (Domains that referr to each other frequently are tagged together)"

    def handle(self, *args, **options):
        DOMAINS_NUMBER = 100
        SENSITIVITY = 0.9

        @async_to_sync
        async def get_domain_connections():
            domain_connections = {}
                
            @sync_to_async
            def get_reffers(domain):

                reffers_to = list(map(lambda referral: referral.destination_domain, list(domain.referrs_to.filter(destination_domain__in=included_domains).exclude(destination_domain=domain))))
                reffers_from = list(map(lambda referral: referral.source_domain, list(domain.referrs_from.filter(source_domain__in=included_domains).exclude(source_domain=domain))))

                connections = reffers_to + reffers_from
                
                connections_set = set(connections)

                connection_count = []
                for connection in connections_set:
                    connection_count.append({
                        "url": connection.url,
                        "count": connections.count(connection),
                        "strength": connections.count(connection)/len(connections),
                    })
                    #print(f' - {connection}')

                domain_connections[domain.url] = {
                    "title": domain.title,
                    "description": domain.description,
                    "connections": connection_count,
                    "total_connections": len(connections),
                    }

            start = timezone.now()
            included_domains = Domain.objects.filter(is_redirect=False, is_source=True).exclude(time_last_requested=None).order_by(F("time_updated").desc(nulls_last=True))
            
            tasks = []
            async for domain in included_domains:
                #tasks.append(asyncio.create_task(get_reffers(domain)))
                await get_reffers(domain)
            #await asyncio.gather(*tasks)

            print((timezone.now() - start).total_seconds())
            '''
            print("---")
            for domain in domain_connections.keys():
                for connection in domain_connections[domain]["connections"]:
                    print(f' - {connection["url"]} {connection["count"]}, {connection["strength"]}')
            '''
            return domain_connections

        def get_match(index, clusters, domain_connections):
            cluster = clusters[index]

            best_match = None
            best_match_strength = None

            for other_cluster_index in range(len(clusters)):
                if other_cluster_index == index:
                    continue

                other_cluster = clusters[other_cluster_index]

                connected = {}
                for domain in cluster:
                    for connection in domain_connections[domain]["connections"]:

                        if connection["url"] in other_cluster:
                            path_weight = (domain_connections[domain]["total_connections"] - connection["count"]) / domain_connections[domain]["total_connections"] 

                            if connection["url"] in connected:
                                if connected[connection["url"]] < path_weight:
                                      continue
                            #print(f'{domain} to {connection["url"]} {path_weight}')
                            connected[connection["url"]] = path_weight

                if len(connected.keys()) == 0:
                    continue
         
                while len(connected.keys()) < len(cluster):
                    for reached in connected.keys():
                        new_connections = {}
                        for connection in domain_connections[reached]["connections"]:  
                            if connection["url"] in cluster:
                                path_weight = connected[reached] + (domain_connections[reached]["total_connections"]-connection["count"]) / domain_connections[reached]["total_connections"]

                                if connection["url"] in connected:
                                    if connected[connection["url"]] < path_weight:
                                        continue
                                
                                    connected[connection["url"]] = path_weight
                                else:
                                    if connection["url"] in new_connections:
                                        if new_connections[connection["url"]] < path_weight:
                                            continue
                                    new_connections[connection["url"]] = path_weight

                    if len(new_connections.keys()) == 0:
                        break
                    for new_connection in new_connections.keys():
                        connected[new_connection] = new_connections[new_connection]

                if len(connected.keys()) == len(cluster):
                    max_path = sorted(connected, key=connected.get, reverse=True)[0]
                    match_strength = connected[max_path]

                    #print(f'match strength: {match_strength}')

                    if best_match != None:
                        if best_match_strength < match_strength:
                            continue

                    best_match = other_cluster_index
                    best_match_strength = match_strength
            
            if best_match != None:
                return {"cluster": index, "match": best_match, "strength": best_match_strength}
            else:
                return {"cluster": index, "match": None, "strength": None}

        def name_clusters(clusters, domain_connections):
            def get_bag_of_words(cluster):
                words = []
                words_by_domain = []
                for domain in cluster:
                    domain_words = []
                    if domain_connections[domain]["description"] != None:
                        domain_words = domain_words + re.sub(r'[^a-zA-Z0-9\s]', '', domain_connections[domain]["description"]).lower().split(" ")
                    if domain_connections[domain]["title"] != None:
                        domain_words = domain_words + re.sub(r'[^a-zA-Z0-9\s]', '', domain_connections[domain]["title"]).lower().split(" ")
                    
                    words = words + domain_words
                    words_by_domain.append(domain_words)

                words_set = set(words)

                bag = {}
                for word in words_set:
                    domain_count = sum([1 if word in domain_word else 0 for domain_word in words_by_domain])
                    if domain_count > 1:
                        bag[word] = words.count(word)
                    
                return bag

            print("get names")
            bags = []
            for i in range(len(clusters)):
                bags.append(get_bag_of_words(clusters[i]))

            total_bag = {}
            for bag in bags:
                for word in bag.keys():
                    if not word in total_bag:
                        total_bag[word] = 0

                    total_bag[word] += bag[word]

            for bag in bags:
                for word in bag.keys():
                    bag[word] = bag[word]/total_bag[word]

            def get_best_word(bag):
                return " ".join(sorted(bag, key=bag.get, reverse=True)[0:5])


            names = list(map(get_best_word, bags))
            print(names)
            return names

        def cluster_with_sensativity(clusters, names, domain_connections, sensativity):
            deeplist = [[cluster] for cluster in clusters]
            names = [[name] for name in names]
            while True:
                best_match = None

                #print(f'{len(clusters)} clusters')
                matches = []
                for i in range(len(clusters)):
                    match = get_match(i, clusters, domain_connections)

                    if match["strength"] == None:
                        continue

                    matches.append(match)

                    if best_match != None:
                        if match["strength"] > best_match["strength"]:
                            continue
                    best_match = match

                if best_match == None:
                    return clusters, deeplist, names

                if best_match["strength"] > sensativity:
                    return clusters, deeplist, names

                print(f'({best_match["strength"]}) {clusters[best_match["cluster"]]} {clusters[best_match["match"]]}')

                def merge_two_clusters(array, a, b):
                    if a < b:
                        array[a] = array[a] + array[b]
                        array.pop(b)
                    else:
                        array[b] = array[b] + array[a]
                        array.pop(a)                

                merge_two_clusters(clusters, best_match["cluster"], best_match["match"])
                merge_two_clusters(deeplist, best_match["cluster"], best_match["match"])
                merge_two_clusters(names, best_match["cluster"], best_match["match"])

        domain_connections = get_domain_connections()
        clusters = list(map(lambda domain: [domain], domain_connections.keys()))
        names = domain_connections.keys()

        rounds = {}
        sensativity = 0.9
        while len(clusters) > 1:
            
            new_clusters, deeplist, prev_names = cluster_with_sensativity(copy.deepcopy(clusters), names, domain_connections, sensativity=sensativity)

            if len(new_clusters) == len(clusters):
                break

            #new_clusters = sorted(new_clusters, key=lambda cluster: len(cluster))
            names = name_clusters(new_clusters, domain_connections)

            for i in range(len(deeplist)):
                print(f"cluster '{names[i]}' ({len(new_clusters[i])})")
                for cluster in deeplist[i]:
                    print(f"---")
                    for domain in cluster:
                        print(f" - {domain}")

            for i in range(len(deeplist)):
                if len(deeplist[i]) > 1:
                
                    if ThothTag.objects.filter(name=names[i]).exists():
                        new_tag = ThothTag.objects.get(name=names[i])
                    else:
                        new_tag = ThothTag.objects.create(name=names[i])
                    
                    print(names[i])
                    print(prev_names[i])

                    for c in range(len(deeplist[i])):

                        cluster = deeplist[i][c]
                        is_direct = False
                        if len(cluster) == 1:
                            is_direct = True

                        if not is_direct:
                            print(f' - {prev_names[i][c]}')
                            if ThothTag.objects.filter(name=prev_names[i][c]).exists():
                                ThothTag.objects.get(name=prev_names[i][c]).parents.add(new_tag)
                            else:
                                print("what the heck???????")

                        for domain in cluster:
                            domainObject = Domain.objects.get(url=domain)
                            if not names[i] in domainObject.tags.names():
                                domainObject.tags.add(names[i], through_defaults={"is_direct": is_direct})

            round = {}
            for i in range(len(new_clusters)):
                round[names[i]] = new_clusters[i]

            rounds[sensativity] = round

            sensativity = sensativity * 2
            clusters = new_clusters

        for tag in ThothTag.objects.all():
            if tag.parents.count() == 0:
                print(tag.name)
                tag.is_top_level = True
                tag.save()

        print("\nrounds:")
        for round in rounds.keys():
            print(round)
            for cluster in rounds[round].keys():
                print(f"cluster '{cluster}' ({len(rounds[round][cluster])})")
                for domain in rounds[round][cluster]:
                    print(f" - {domain}")
    